"""Visualization utilities for HPA-MDO results.

Generates publication-quality plots of structural analysis results,
spanwise load distributions, and optimization convergence.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend for server/CI use
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from hpa_mdo.structure.beam_model import BeamResult
from hpa_mdo.structure.optimizer import OptimizationResult


def plot_beam_result(
    result: BeamResult,
    E: float,
    sigma_allow: float | None = None,
    title: str = "Beam Analysis Results",
    save_path: str | Path | None = None,
) -> None:
    """Plot shear, moment, deflection, and stress along the span."""
    if not HAS_MPL:
        raise RuntimeError("matplotlib not installed")

    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(2, 3, figure=fig, hspace=0.35, wspace=0.35)
    fig.suptitle(title, fontsize=14, fontweight="bold")

    y = result.y

    # 1. Shear Force
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(y, result.shear, "b-", linewidth=1.5)
    ax1.set_xlabel("Span y [m]")
    ax1.set_ylabel("Shear Force [N]")
    ax1.set_title("Shear Force Distribution")
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="k", linewidth=0.5)

    # 2. Bending Moment
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(y, result.moment, "r-", linewidth=1.5)
    ax2.set_xlabel("Span y [m]")
    ax2.set_ylabel("Bending Moment [N·m]")
    ax2.set_title("Bending Moment Distribution")
    ax2.grid(True, alpha=0.3)

    # 3. Deflection
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.plot(y, result.deflection * 1000, "g-", linewidth=1.5)
    ax3.set_xlabel("Span y [m]")
    ax3.set_ylabel("Deflection [mm]")
    ax3.set_title(f"Deflection (tip = {result.tip_deflection*1000:.1f} mm)")
    ax3.grid(True, alpha=0.3)

    # 4. Bending Stress
    ax4 = fig.add_subplot(gs[1, 0])
    actual_stress = result.stress * E / 1e6  # MPa
    ax4.plot(y, actual_stress, "m-", linewidth=1.5)
    if sigma_allow is not None:
        ax4.axhline(y=sigma_allow / 1e6, color="r", linestyle="--",
                     label=f"Allowable = {sigma_allow/1e6:.0f} MPa")
        ax4.legend(fontsize=9)
    ax4.set_xlabel("Span y [m]")
    ax4.set_ylabel("Bending Stress [MPa]")
    ax4.set_title("Max Bending Stress")
    ax4.grid(True, alpha=0.3)

    # 5. EI distribution
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.plot(y, result.EI, "c-", linewidth=1.5)
    ax5.set_xlabel("Span y [m]")
    ax5.set_ylabel("EI [N·m²]")
    ax5.set_title("Flexural Rigidity")
    ax5.grid(True, alpha=0.3)

    # 6. External load
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.plot(y, result.f_ext, "k-", linewidth=1.5)
    ax6.fill_between(y, result.f_ext, alpha=0.15, color="blue")
    ax6.set_xlabel("Span y [m]")
    ax6.set_ylabel("Net Force/Span [N/m]")
    ax6.set_title("Applied Load Distribution")
    ax6.grid(True, alpha=0.3)
    ax6.axhline(y=0, color="k", linewidth=0.5)

    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    else:
        plt.show()

    plt.close(fig)


def plot_spar_geometry(
    y: np.ndarray,
    outer_d: np.ndarray,
    inner_d: np.ndarray,
    wall_thickness: np.ndarray,
    title: str = "Spar Geometry",
    save_path: str | Path | None = None,
) -> None:
    """Plot spar cross-section dimensions along the span."""
    if not HAS_MPL:
        raise RuntimeError("matplotlib not installed")

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    fig.suptitle(title, fontsize=13, fontweight="bold")

    axes[0].plot(y, outer_d * 1000, "b-", label="Outer ⌀", linewidth=1.5)
    axes[0].plot(y, inner_d * 1000, "r--", label="Inner ⌀", linewidth=1.5)
    axes[0].set_xlabel("Span y [m]")
    axes[0].set_ylabel("Diameter [mm]")
    axes[0].set_title("Tube Diameters")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(y, wall_thickness * 1000, "g-", linewidth=1.5)
    axes[1].set_xlabel("Span y [m]")
    axes[1].set_ylabel("Wall Thickness [mm]")
    axes[1].set_title("Wall Thickness")
    axes[1].grid(True, alpha=0.3)

    area = np.pi / 4 * (outer_d**2 - inner_d**2)
    axes[2].plot(y, area * 1e6, "m-", linewidth=1.5)
    axes[2].set_xlabel("Span y [m]")
    axes[2].set_ylabel("Area [mm²]")
    axes[2].set_title("Cross-Section Area")
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    else:
        plt.show()
    plt.close(fig)


def print_optimization_summary(result: OptimizationResult) -> str:
    """Generate a formatted text summary of optimization results."""
    lines = [
        "=" * 60,
        "  HPA-MDO Spar Optimization Results",
        "=" * 60,
        f"  Status:           {'CONVERGED' if result.success else 'FAILED'}",
        f"  Message:          {result.message}",
        "-" * 60,
        f"  Spar Mass (full): {result.spar_mass_full_kg:.3f} kg",
        f"  Spar Mass (half): {result.spar_mass_kg:.3f} kg",
        "-" * 60,
        f"  d_i root:         {result.d_i_root*1000:.2f} mm",
        f"  d_i tip:          {result.d_i_tip*1000:.2f} mm",
        "-" * 60,
        f"  Tip Deflection:   {result.tip_deflection_m*1000:.1f} mm"
        f"  ({result.tip_deflection_m:.4f} m)",
        f"  Max Stress:       {result.max_stress_Pa/1e6:.1f} MPa",
        f"  Allowable Stress: {result.allowable_stress_Pa/1e6:.1f} MPa",
        f"  Stress Margin:    {(1.0 - result.max_stress_Pa/result.allowable_stress_Pa)*100:.1f}%",
        "=" * 60,
    ]
    summary = "\n".join(lines)
    return summary
