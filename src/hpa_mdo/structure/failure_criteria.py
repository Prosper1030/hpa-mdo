"""Pure-function composite failure criteria for spar tube elements.

Tube stress state assumptions
------------------------------
CF tube with isotropic-equivalent or UD layup oriented along the beam axis.

    σ₁  — fibre-direction (longitudinal) stress  = bending + axial pre-stress [Pa]
    σ₂  — transverse (hoop) stress               ≈ 0 for thin-wall tubes
    τ₁₂ — in-plane shear stress                  = torsion surface shear [Pa]

Because σ₂ ≈ 0 the interaction term in Tsai-Hill simplifies, and the linear
term F2·σ₂ in Tsai-Wu vanishes.  Both are handled correctly by the general
formulas below (passing σ₂=0).

Failure index conventions
--------------------------
All functions return a dimensionless failure index FI:
    FI ≤ 0 → safe
    FI  > 0 → failed

This matches the KS-aggregation convention used by KSFailureComp.

References
----------
[1] Tsai, S.W. & Wu, E.M. (1971).  J. Composite Materials 5, 58–80.
[2] Tsai, S.W. & Hill, R. (1950).  Theory of yielding applied to UD composites.
"""
from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Helper: sign-aware strength selector (complex-step safe)
# ---------------------------------------------------------------------------

def _cs_abs(x: "np.ndarray") -> "np.ndarray":
    """Complex-step-safe absolute value: sqrt(x² + ε)."""
    return np.sqrt(x * x + 1e-30)


# ---------------------------------------------------------------------------
# Tsai-Hill criterion
# ---------------------------------------------------------------------------

def tsai_hill_index(
    sigma1: "np.ndarray",
    sigma2: "np.ndarray",
    tau12: "np.ndarray",
    F1t: float,
    F1c: float,
    F2t: float,
    F2c: float,
    F6: float,
) -> "np.ndarray":
    """Tsai-Hill failure index per element.

    FI_TH = (σ₁/X)² - σ₁·σ₂/X² + (σ₂/Y)² + (τ/F₆)² - 1

    where X = F1t if σ₁ ≥ 0 else F1c, Y = F2t if σ₂ ≥ 0 else F2c.

    Returns FI_TH (scalar or array); FI ≤ 0 ↔ safe.

    Complex-step compatible: the sign branches use np.where on real parts,
    leaving imaginary perturbations in the quadratic terms.
    """
    sigma1 = np.asarray(sigma1)
    sigma2 = np.asarray(sigma2)
    tau12 = np.asarray(tau12)

    # Branch on real part only (complex-step safe)
    X = np.where(np.real(sigma1) >= 0.0, F1t, F1c)
    Y = np.where(np.real(sigma2) >= 0.0, F2t, F2c)

    fi = (
        (sigma1 / X) ** 2
        - sigma1 * sigma2 / (X ** 2)
        + (sigma2 / Y) ** 2
        + (tau12 / F6) ** 2
        - 1.0
    )
    return fi


# ---------------------------------------------------------------------------
# Tsai-Wu criterion
# ---------------------------------------------------------------------------

def tsai_wu_index(
    sigma1: "np.ndarray",
    sigma2: "np.ndarray",
    tau12: "np.ndarray",
    F1t: float,
    F1c: float,
    F2t: float,
    F2c: float,
    F6: float,
) -> "np.ndarray":
    """Tsai-Wu failure index per element.

    FI_TW = F11·σ₁² + F22·σ₂² + F66·τ² + 2·F12·σ₁·σ₂ + F1·σ₁ + F2·σ₂ - 1

    Tsai-Hahn interaction: F12 = -½·√(F11·F22)

    Parameters
    ----------
    sigma1 : array [Pa]  Longitudinal (fibre-direction) stress.
    sigma2 : array [Pa]  Transverse (matrix-direction) stress.  Pass zeros for tubes.
    tau12  : array [Pa]  In-plane shear stress.
    F1t, F1c : float [Pa]  Tensile / compressive fibre strengths (positive magnitudes).
    F2t, F2c : float [Pa]  Tensile / compressive transverse strengths.
    F6   : float [Pa]  In-plane shear strength.

    Returns
    -------
    fi : array  FI ≤ 0 ↔ safe.
    """
    sigma1 = np.asarray(sigma1)
    sigma2 = np.asarray(sigma2)
    tau12 = np.asarray(tau12)

    # Tensor polynomial coefficients
    F11 = 1.0 / (F1t * F1c)
    F22 = 1.0 / (F2t * F2c)
    F66 = 1.0 / (F6 * F6)
    F1_lin = 1.0 / F1t - 1.0 / F1c      # linear term coefficient
    F2_lin = 1.0 / F2t - 1.0 / F2c
    F12 = -0.5 * np.sqrt(F11 * F22)     # Tsai-Hahn interaction

    fi = (
        F11 * sigma1 ** 2
        + F22 * sigma2 ** 2
        + F66 * tau12 ** 2
        + 2.0 * F12 * sigma1 * sigma2
        + F1_lin * sigma1
        + F2_lin * sigma2
        - 1.0
    )
    return fi
