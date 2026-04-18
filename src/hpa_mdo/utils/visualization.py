"""Visualization utilities for HPA-MDO results.

Generates publication-quality plots of structural analysis results,
spanwise load distributions, and optimization convergence.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for server/CI use
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.structure.spar_model import segment_boundaries_from_lengths


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _append_layup_block(lines: list, title: str, layup) -> None:
    """Append a per-segment discrete layup schedule block to ``lines``."""
    if not layup:
        return
    lines.append(f"  {title}:")
    for seg in layup:
        stack = seg.stack
        n_plies = stack.total_plies()
        t_mm = seg.equivalent_properties.wall_thickness * 1000.0
        notation = seg.stack_notation
        tw = seg.tsai_wu_summary
        if tw is not None:
            sr = tw.min_strength_ratio
            if not math.isfinite(sr):
                sr_str = "SR=inf"
                safe = "SAFE"
            else:
                sr_str = f"SR={sr:.2f}"
                safe = "SAFE" if sr >= 1.0 else "VIOLATED"
            tw_part = f" TW_{sr_str} ({safe})"
        else:
            tw_part = ""
        capped = " [catalog max]" if seg.catalog_capped else ""
        lines.append(
            f"    Seg {seg.segment_index} "
            f"({seg.y_start_m:.2f}-{seg.y_end_m:.2f} m): "
            f"{notation:<22s} n={n_plies:>2d}, t={t_mm:5.2f} mm,{tw_part}{capped}"
        )


def _append_discrete_final_design_block(
    lines: list[str],
    summary: dict[str, object],
    artifact_path: str | None,
) -> None:
    """Append the top-level discrete final-design verdict to ``lines``."""
    if not summary:
        return

    overall = str(summary.get("overall_status", "unknown")).upper()
    manufacturing = "PASS" if bool(summary.get("manufacturing_gates_passed", True)) else "FAIL"
    lines += [
        "-" * 64,
        "  DISCRETE FINAL DESIGN",
        "-" * 64,
        f"  Overall status : {overall}",
        f"  Design layer   : {summary.get('design_layer', 'discrete_final')}",
        f"  Manufacturing  : {manufacturing}",
    ]

    critical_strength = summary.get("critical_strength_ratio")
    if isinstance(critical_strength, dict) and critical_strength.get("value") is not None:
        spar = critical_strength.get("spar") or "unknown"
        seg = critical_strength.get("segment_index")
        seg_suffix = "" if seg in (None, "") else f" seg {int(seg)}"
        lines.append(
            f"  Critical SR    : {float(critical_strength['value']):.3f} @ {spar}{seg_suffix}"
        )

    critical_failure = summary.get("critical_failure_index")
    if isinstance(critical_failure, dict) and critical_failure.get("value") is not None:
        spar = critical_failure.get("spar") or "unknown"
        seg = critical_failure.get("segment_index")
        seg_suffix = "" if seg in (None, "") else f" seg {int(seg)}"
        lines.append(
            f"  Critical FI    : {float(critical_failure['value']):.3f} @ {spar}{seg_suffix}"
        )

    spars = summary.get("spars")
    if isinstance(spars, dict) and spars:
        status_parts = []
        for spar_name, spar_summary in spars.items():
            if not isinstance(spar_summary, dict):
                continue
            status_parts.append(f"{spar_name}={str(spar_summary.get('status', 'unknown')).upper()}")
        if status_parts:
            lines.append(f"  Spar statuses  : {', '.join(status_parts)}")

    structural_recheck = summary.get("structural_recheck")
    if isinstance(structural_recheck, dict) and structural_recheck:
        recheck_status = str(
            structural_recheck.get(
                "status",
                "pass" if bool(structural_recheck.get("success", False)) else "fail",
            )
        ).upper()
        if recheck_status == "SKIPPED":
            reason = structural_recheck.get("message", "not available")
            lines.append(f"  Structural recheck: SKIPPED ({reason})")
        else:
            lines.append(
                "  Structural recheck: "
                f"{recheck_status}, mass={float(structural_recheck.get('total_mass_full_kg', 0.0)):.3f} kg, "
                f"FI={float(structural_recheck.get('failure_index', 0.0)):.5f}, "
                f"buckling={float(structural_recheck.get('buckling_index', 0.0)):.5f}, "
                f"twist={float(structural_recheck.get('twist_max_deg', 0.0)):.3f} deg, "
                f"defl={float(structural_recheck.get('tip_deflection_m', 0.0)):.5f} m"
            )
            failed_checks = structural_recheck.get("failed_checks")
            if isinstance(failed_checks, list) and failed_checks:
                lines.append(
                    "  Structural gates: "
                    + ", ".join(str(check) for check in failed_checks)
                )

    selection_signal = summary.get("selection_signal")
    if isinstance(selection_signal, dict) and selection_signal:
        status = str(selection_signal.get("status", "unknown")).upper()
        outer_loop_action = str(selection_signal.get("outer_loop_action", "unknown"))
        handoff_ready = "YES" if bool(selection_signal.get("handoff_ready", False)) else "NO"
        lines.append(
            f"  Selection signal: {status} (outer-loop={outer_loop_action}, handoff={handoff_ready})"
        )
        blocking_reasons = selection_signal.get("blocking_reasons")
        if isinstance(blocking_reasons, list) and blocking_reasons:
            lines.append(
                "  Blocking reasons: "
                + ", ".join(str(reason) for reason in blocking_reasons)
            )
        warning_reasons = selection_signal.get("warning_reasons")
        if isinstance(warning_reasons, list) and warning_reasons:
            lines.append(
                "  Warning reasons : "
                + ", ".join(str(reason) for reason in warning_reasons)
            )

    if artifact_path:
        lines.append(f"  JSON artifact  : {artifact_path}")


def _step_xy(seg_boundaries: np.ndarray, values: np.ndarray):
    """Return (x, y) arrays for a step-function plot.

    Each segment i is constant between seg_boundaries[i] and
    seg_boundaries[i+1].  Returns arrays suitable for ax.plot().
    """
    x = []
    y = []
    for i, v in enumerate(values):
        x.extend([seg_boundaries[i], seg_boundaries[i + 1]])
        y.extend([v, v])
    return np.array(x), np.array(y)


# ---------------------------------------------------------------------------
# A. Beam analysis figure
# ---------------------------------------------------------------------------

def plot_beam_analysis(
    result: OptimizationResult,
    y_nodes: np.ndarray,
    output_dir: Union[Path, str],
) -> None:
    """Plot flapwise deflection, twist, and stress from an OptimizationResult.

    Parameters
    ----------
    result : OptimizationResult
    y_nodes : np.ndarray, shape (nn,)
        Spanwise node positions [m].
    output_dir : Path or str
        Directory where ``beam_analysis.png`` will be saved.
    """
    if not HAS_MPL:
        raise RuntimeError("matplotlib not installed — cannot generate plots")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(16, 10))
    gs = GridSpec(2, 3, figure=fig, hspace=0.40, wspace=0.35)
    fig.suptitle("HPA-MDO Beam Analysis Results", fontsize=14, fontweight="bold")

    has_disp = result.disp is not None

    # ── 1. Flapwise deflection ────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    if has_disp:
        defl_mm = result.disp[:, 2] * 1000.0
        ax1.plot(y_nodes, defl_mm, "b-", linewidth=1.8)
        ax1.set_ylabel("Deflection [mm]")
    else:
        ax1.text(0.5, 0.5, "No displacement data",
                 ha="center", va="center", transform=ax1.transAxes, color="gray")
    ax1.set_xlabel("Span y [m]")
    ax1.set_title("Flapwise Deflection")
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="k", linewidth=0.5)

    # ── 2. Twist angle ────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    if has_disp:
        # TODO: project to local beam axis to match TwistConstraintComp.
        # For straight wings (no sweep/dihedral) this is identical to disp[:, 4],
        # but for future swept-wing support we should use the same rotation matrix
        # that TwistConstraintComp applies. Tracked: M2 hygiene pack note.
        twist_deg = result.disp[:, 4] * (180.0 / math.pi)
        ax2.plot(y_nodes, twist_deg, "r-", linewidth=1.8)
        ax2.set_ylabel("Twist [deg]")
        ax2.axhline(y=0, color="k", linewidth=0.5)
    else:
        ax2.text(0.5, 0.5, "No displacement data",
                 ha="center", va="center", transform=ax2.transAxes, color="gray")
    ax2.set_xlabel("Span y [m]")
    ax2.set_title(f"Twist (max={result.twist_max_deg:.2f} deg)")
    ax2.grid(True, alpha=0.3)

    # ── 3. Von Mises — main spar ──────────────────────────────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    if result.vonmises_main is not None and len(result.vonmises_main) > 0:
        y_elem = (y_nodes[:-1] + y_nodes[1:]) / 2.0
        vm_mpa = result.vonmises_main / 1e6
        ax3.plot(y_elem, vm_mpa, "m-", linewidth=1.8, label="Von Mises")
        allow_mpa = result.allowable_stress_main_Pa / 1e6
        ax3.axhline(y=allow_mpa, color="r", linestyle="--",
                    label=f"Allowable = {allow_mpa:.0f} MPa")
        ax3.legend(fontsize=8)
        ax3.set_ylabel("Stress [MPa]")
    else:
        ax3.text(0.5, 0.5, "No stress data",
                 ha="center", va="center", transform=ax3.transAxes, color="gray")
    ax3.set_xlabel("Span y [m]")
    ax3.set_title("Von Mises Stress — Main Spar")
    ax3.grid(True, alpha=0.3)

    # ── 4. Von Mises — rear spar (or failure index text) ─────────────────
    ax4 = fig.add_subplot(gs[1, 0])
    if result.vonmises_rear is not None and len(result.vonmises_rear) > 0:
        y_elem = (y_nodes[:-1] + y_nodes[1:]) / 2.0
        vm_mpa = result.vonmises_rear / 1e6
        ax4.plot(y_elem, vm_mpa, "c-", linewidth=1.8, label="Von Mises")
        allow_mpa = result.allowable_stress_rear_Pa / 1e6
        ax4.axhline(y=allow_mpa, color="r", linestyle="--",
                    label=f"Allowable = {allow_mpa:.0f} MPa")
        ax4.legend(fontsize=8)
        ax4.set_ylabel("Stress [MPa]")
        ax4.set_title("Von Mises Stress — Rear Spar")
    else:
        status = "SAFE" if result.failure_index <= 0 else "VIOLATED"
        ax4.text(
            0.5, 0.5,
            f"Failure index: {result.failure_index:.4f}\n({status})",
            ha="center", va="center", transform=ax4.transAxes,
            fontsize=12,
            color="green" if result.failure_index <= 0 else "red",
        )
        ax4.set_title("Failure Index (no rear spar data)")
    ax4.set_xlabel("Span y [m]")
    ax4.grid(True, alpha=0.3)

    # ── 5. Applied loads placeholder ──────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.text(
        0.5, 0.5, "Loads from VSPAero\n(see run_optimization.py for details)",
        ha="center", va="center", transform=ax5.transAxes,
        fontsize=11, color="gray",
    )
    ax5.set_title("Applied Loads")
    ax5.set_xlabel("Span y [m]")
    ax5.grid(True, alpha=0.3)

    # ── 6. Mass summary ───────────────────────────────────────────────────
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.axis("off")
    feasible = (
        result.success
        and (
            getattr(result, "max_twist_limit_deg", None) is None
            or result.twist_max_deg <= result.max_twist_limit_deg * 1.02
        )
        and
        result.failure_index <= 0
        and result.buckling_index <= 0
        and (result.max_tip_deflection_m is None or result.tip_deflection_m <= result.max_tip_deflection_m * 1.02)
    )
    if result.success and feasible:
        status_str = "CONVERGED (Feasible)"
    elif result.success:
        status_str = "CONVERGED (Infeasible)"
    else:
        status_str = "FAILED"
        
    twist_line = f"Max twist:      {result.twist_max_deg:.2f} deg"
    if getattr(result, "max_twist_limit_deg", None) is not None:
        twist_status = (
            "OK"
            if result.twist_max_deg <= result.max_twist_limit_deg * 1.02
            else "VIOLATED"
        )
        twist_line += f" / MAX: {result.max_twist_limit_deg:.2f} deg ({twist_status})"

    summary_text = (
        f"Mass Summary\n"
        f"{'=' * 30}\n"
        f"Total mass (full): {result.total_mass_full_kg:.3f} kg\n"
        f"Spar mass (full):  {result.spar_mass_full_kg:.3f} kg\n"
        f"Spar mass (half):  {result.spar_mass_half_kg:.3f} kg\n\n"
        f"Status: {status_str}\n"
        f"{result.message}\n\n"
        f"Tip deflection: {result.tip_deflection_m * 1000:.1f} mm\n"
        f"{twist_line}\n"
        f"Failure index:  {result.failure_index:.4f}\n"
        f"Buckling index: {result.buckling_index:.4f}"
    )
    ax6.text(
        0.05, 0.95, summary_text,
        transform=ax6.transAxes,
        verticalalignment="top",
        fontsize=9,
        fontfamily="monospace",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.4),
    )
    ax6.set_title("Mass & Convergence")

    save_path = output_dir / "beam_analysis.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# B. Spar geometry figure
# ---------------------------------------------------------------------------

def plot_spar_geometry(
    result: OptimizationResult,
    y_nodes: np.ndarray,
    seg_lengths: List[float],
    output_dir: Union[Path, str],
) -> None:
    """Plot spar cross-section geometry (OD, wall thickness, ID, area).

    Parameters
    ----------
    result : OptimizationResult
    y_nodes : np.ndarray, shape (nn,)
        Spanwise node positions [m].
    seg_lengths : list of float
        Segment lengths [m], e.g. [1.5, 3.0, 3.0, 3.0, 3.0, 3.0].
    output_dir : Path or str
        Directory where ``spar_geometry.png`` will be saved.
    """
    if not HAS_MPL:
        raise RuntimeError("matplotlib not installed — cannot generate plots")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seg_bounds = segment_boundaries_from_lengths(seg_lengths)

    # Retrieve radius arrays (may not exist on older results)
    main_r = getattr(result, "main_r_seg_mm", None)
    rear_r = getattr(result, "rear_r_seg_mm", None)
    main_t = result.main_t_seg_mm          # always present
    rear_t = result.rear_t_seg_mm          # may be None

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("HPA-MDO Spar Geometry (Optimized)", fontsize=14, fontweight="bold")

    # Helper: draw one step-function curve if data available
    def _draw_step(ax, seg_values, label, color, linestyle="-"):
        if seg_values is None:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, color="gray")
            return
        x, y = _step_xy(seg_bounds, seg_values)
        ax.plot(x, y, color=color, linestyle=linestyle, linewidth=1.8, label=label)

    # ── 1. Outer Diameter ─────────────────────────────────────────────────
    ax = axes[0, 0]
    if main_r is not None:
        main_od = main_r * 2.0
        _draw_step(ax, main_od, "Main spar OD", "steelblue")
        if rear_r is not None:
            rear_od = rear_r * 2.0
            _draw_step(ax, rear_od, "Rear spar OD", "darkorange", "--")
        ax.legend(fontsize=9)
    else:
        ax.text(0.5, 0.5, "OD data not available\n(main_r_seg_mm field missing)",
                ha="center", va="center", transform=ax.transAxes, color="gray")
    ax.set_xlabel("Span y [m]")
    ax.set_ylabel("Outer Diameter [mm]")
    ax.set_title("Outer Diameter vs Span")
    ax.grid(True, alpha=0.3)

    # ── 2. Wall Thickness ─────────────────────────────────────────────────
    ax = axes[0, 1]
    _draw_step(ax, main_t, "Main spar", "steelblue")
    if rear_t is not None:
        _draw_step(ax, rear_t, "Rear spar", "darkorange", "--")
    if main_t is not None or rear_t is not None:
        ax.legend(fontsize=9)
    ax.set_xlabel("Span y [m]")
    ax.set_ylabel("Wall Thickness [mm]")
    ax.set_title("Wall Thickness vs Span")
    ax.grid(True, alpha=0.3)

    # ── 3. Inner Diameter = OD - 2*t ─────────────────────────────────────
    ax = axes[1, 0]
    if main_r is not None and main_t is not None:
        main_id = main_r * 2.0 - 2.0 * main_t
        _draw_step(ax, main_id, "Main spar ID", "steelblue")
        if rear_r is not None and rear_t is not None:
            rear_id = rear_r * 2.0 - 2.0 * rear_t
            _draw_step(ax, rear_id, "Rear spar ID", "darkorange", "--")
        ax.legend(fontsize=9)
    else:
        ax.text(0.5, 0.5, "OD data not available\n(cannot compute ID)",
                ha="center", va="center", transform=ax.transAxes, color="gray")
    ax.set_xlabel("Span y [m]")
    ax.set_ylabel("Inner Diameter [mm]")
    ax.set_title("Inner Diameter vs Span")
    ax.grid(True, alpha=0.3)

    # ── 4. Cross-section Area = pi/4*(OD^2 - ID^2) ───────────────────────
    ax = axes[1, 1]
    if main_r is not None and main_t is not None:
        main_od = main_r * 2.0
        main_id = main_od - 2.0 * main_t
        main_area = (math.pi / 4.0) * (main_od ** 2 - main_id ** 2)
        _draw_step(ax, main_area, "Main spar", "steelblue")
        if rear_r is not None and rear_t is not None:
            rear_od = rear_r * 2.0
            rear_id = rear_od - 2.0 * rear_t
            rear_area = (math.pi / 4.0) * (rear_od ** 2 - rear_id ** 2)
            _draw_step(ax, rear_area, "Rear spar", "darkorange", "--")
        ax.legend(fontsize=9)
    else:
        ax.text(0.5, 0.5, "OD data not available\n(cannot compute area)",
                ha="center", va="center", transform=ax.transAxes, color="gray")
    ax.set_xlabel("Span y [m]")
    ax.set_ylabel("Cross-section Area [mm\u00b2]")
    ax.set_title("Cross-section Area vs Span")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    save_path = output_dir / "spar_geometry.png"
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# C. Text summary
# ---------------------------------------------------------------------------

def write_optimization_summary(
    result: OptimizationResult,
    path: Optional[Union[Path, str]],
) -> str:
    """Write a plain-text summary of optimization results.

    Parameters
    ----------
    result : OptimizationResult
    path : Path, str, or None
        File path to write.  Pass ``None`` to skip writing (summary is
        still returned as a string).

    Returns
    -------
    str
        The formatted summary string.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    feasible = (
        result.success
        and (
            getattr(result, "max_twist_limit_deg", None) is None
            or result.twist_max_deg <= result.max_twist_limit_deg * 1.02
        )
        and
        result.failure_index <= 0
        and result.buckling_index <= 0
        and (result.max_tip_deflection_m is None or result.tip_deflection_m <= result.max_tip_deflection_m * 1.02)
    )
    if result.success and feasible:
        status = "CONVERGED (Feasible)"
    elif result.success:
        status = "CONVERGED (Infeasible)"
    else:
        status = "FAILED"

    # ── Header ────────────────────────────────────────────────────────────
    lines = [
        "=" * 64,
        "  HPA-MDO Spar Optimization Summary",
        f"  Generated: {ts}",
        "=" * 64,
        f"  Status          : {status}",
        f"  Message         : {result.message}",
        "-" * 64,
        "  MASS BREAKDOWN",
        "-" * 64,
        f"  Spar mass (half): {result.spar_mass_half_kg:.4f} kg",
        f"  Spar mass (full): {result.spar_mass_full_kg:.4f} kg",
        f"  Total mass (full): {result.total_mass_full_kg:.4f} kg",
        "-" * 64,
        "  STRUCTURAL PERFORMANCE",
        "-" * 64,
    ]
    
    defl_str = f"  Tip deflection  : {result.tip_deflection_m * 1000:.2f} mm  ({result.tip_deflection_m:.5f} m)"
    if result.max_tip_deflection_m is not None:
        defl_status = "OK" if result.tip_deflection_m <= result.max_tip_deflection_m * 1.02 else "VIOLATED"
        defl_str += f" / MAX: {result.max_tip_deflection_m*1000:.1f} mm ({defl_status})"
    lines.append(defl_str)
    
    twist_line = f"  Max twist       : {result.twist_max_deg:.3f} deg"
    if getattr(result, "max_twist_limit_deg", None) is not None:
        twist_status = (
            "OK"
            if result.twist_max_deg <= result.max_twist_limit_deg * 1.02
            else "VIOLATED"
        )
        twist_line += (
            f" / MAX: {result.max_twist_limit_deg:.3f} deg ({twist_status})"
        )

    lines += [
        twist_line,
        f"  Failure index   : {result.failure_index:.5f}  "
        f"({'SAFE' if result.failure_index <= 0 else 'VIOLATED'})",
        f"  Buckling index  : {result.buckling_index:.5f}  "
        f"({'SAFE' if result.buckling_index <= 0 else 'VIOLATED'})",
        "",
        f"  Max stress — main : {result.max_stress_main_Pa / 1e6:.2f} MPa",
        f"  Allowable  — main : {result.allowable_stress_main_Pa / 1e6:.2f} MPa",
        f"  Margin     — main : "
        f"{(1.0 - result.max_stress_main_Pa / (result.allowable_stress_main_Pa + 1e-30)) * 100:.1f}%",
        "",
        f"  Max stress — rear : {result.max_stress_rear_Pa / 1e6:.2f} MPa",
        f"  Allowable  — rear : {result.allowable_stress_rear_Pa / 1e6:.2f} MPa",
    ]
    if result.allowable_stress_rear_Pa > 0 and result.max_stress_rear_Pa > 0:
        margin_rear = (
            1.0 - result.max_stress_rear_Pa / result.allowable_stress_rear_Pa
        ) * 100.0
        lines.append(f"  Margin     — rear : {margin_rear:.1f}%")

    # ── Main spar segment table ───────────────────────────────────────────
    lines += [
        "-" * 64,
        "  MAIN SPAR SEGMENTS",
        "-" * 64,
        f"  {'Seg':>4}  {'t [mm]':>10}  {'OD [mm]':>10}",
    ]
    main_r = getattr(result, "main_r_seg_mm", None)
    for i, t in enumerate(result.main_t_seg_mm):
        od_str = f"{main_r[i] * 2.0:10.3f}" if main_r is not None else "       N/A"
        lines.append(f"  {i + 1:>4}  {t:>10.4f}  {od_str}")

    # ── Rear spar segment table ───────────────────────────────────────────
    if result.rear_t_seg_mm is not None:
        rear_r = getattr(result, "rear_r_seg_mm", None)
        lines += [
            "-" * 64,
            "  REAR SPAR SEGMENTS",
            "-" * 64,
            f"  {'Seg':>4}  {'t [mm]':>10}  {'OD [mm]':>10}",
        ]
        for i, t in enumerate(result.rear_t_seg_mm):
            od_str = f"{rear_r[i] * 2.0:10.3f}" if rear_r is not None else "       N/A"
            lines.append(f"  {i + 1:>4}  {t:>10.4f}  {od_str}")
    else:
        lines += [
            "-" * 64,
            "  REAR SPAR: disabled",
        ]

    manufacturing = getattr(result, "manufacturing_gates", {}) or {}
    if manufacturing:
        status = "PASS" if manufacturing.get("passed", True) else "FAIL"
        lines += [
            "-" * 64,
            "  MANUFACTURING GATES",
            "-" * 64,
            f"  Overall: {status}",
        ]
        for spar_name, gate in (manufacturing.get("spars", {}) or {}).items():
            spar_status = "PASS" if gate.get("passed", True) else "FAIL"
            lines.append(
                f"  {spar_name}: {spar_status}, "
                f"ply-step margin={float(gate.get('ply_count_step_margin_min', 0.0)):+.3f}, "
                f"run-length margin={float(gate.get('run_length_margin_min_m', 0.0)):+.3f} m"
            )

    layup_main = getattr(result, "layup_main", None)
    layup_rear = getattr(result, "layup_rear", None)
    if layup_main or layup_rear:
        lines += [
            "-" * 64,
            "  DISCRETE LAYUP SCHEDULE",
            "-" * 64,
        ]
        _append_layup_block(lines, "Main spar", layup_main)
        if layup_rear:
            _append_layup_block(lines, "Rear spar", layup_rear)
        layup_main_summary = getattr(result, "layup_main_summary", None) or {}
        layup_rear_summary = getattr(result, "layup_rear_summary", None) or {}
        penalty = 0.0
        if isinstance(layup_main_summary, dict):
            penalty += float(layup_main_summary.get("mass_penalty_full_wing_kg", 0.0) or 0.0)
        if isinstance(layup_rear_summary, dict):
            penalty += float(layup_rear_summary.get("mass_penalty_full_wing_kg", 0.0) or 0.0)
        lines.append(
            f"  Total stack mass penalty vs continuous: {penalty:+.3f} kg (full wing)"
        )

    discrete_final_design_summary = getattr(result, "discrete_final_design_summary", None) or {}
    discrete_final_design_json_path = getattr(result, "discrete_final_design_json_path", None)
    if isinstance(discrete_final_design_summary, dict) and discrete_final_design_summary:
        _append_discrete_final_design_block(
            lines,
            discrete_final_design_summary,
            discrete_final_design_json_path,
        )

    timing = getattr(result, "timing_s", {}) or {}
    lines += [
        "-" * 64,
        "  OPTIMIZATION TIMING [s]",
        "-" * 64,
        f"  DE global search : {float(timing.get('de_global_s', 0.0)):.6f}",
        f"  SLSQP local refine: {float(timing.get('slsqp_local_s', 0.0)):.6f}",
        f"  Total            : {float(timing.get('total_s', 0.0)):.6f}",
    ]

    lines.append("=" * 64)
    summary = "\n".join(lines) + "\n"

    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(summary, encoding="utf-8")

    return summary


def print_optimization_summary(result: OptimizationResult) -> str:
    """Print and return a formatted text summary of optimization results."""
    summary = write_optimization_summary(result, None)
    print(summary)
    return summary
