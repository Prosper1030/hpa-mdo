"""Mission-aware Fourier spanload target diagnostics.

The target built here is a reference loading shape for upstream concept search.
It does not select airfoils, alter geometry, or gate candidates; route callers
can compare it against AVL actual loading in shadow mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, pi
from typing import Any, Mapping, Sequence

import numpy as np


FOURIER_TARGET_SOURCE = "mission_contract_fourier_target_v2_shadow_no_ranking_gate"
DEFAULT_OUTER_ETA_MIN = 0.70


@dataclass(frozen=True)
class FourierTarget:
    y: tuple[float, ...]
    eta: tuple[float, ...]
    theta: tuple[float, ...]
    chord_ref: tuple[float, ...]
    gamma_target: tuple[float, ...]
    lprime_target: tuple[float, ...]
    cl_target: tuple[float, ...]
    A1: float
    r3: float
    r5: float
    e_theory: float
    CL_req: float
    AR: float
    outer_lift_fraction: float
    outer_lift_ratio_vs_ellipse: float
    root_bending_proxy: float
    gamma_min: float
    cl_max: float
    source: str
    lift_total_n: float
    lift_error_n: float
    lift_error_fraction: float
    validation_status: str
    validation_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_rows(self) -> list[dict[str, float]]:
        return [
            {
                "eta": float(eta),
                "y": float(y),
                "chord_ref": float(chord),
                "gamma_target": float(gamma),
                "lprime_target": float(lprime),
                "cl_target": float(cl),
            }
            for eta, y, chord, gamma, lprime, cl in zip(
                self.eta,
                self.y,
                self.chord_ref,
                self.gamma_target,
                self.lprime_target,
                self.cl_target,
                strict=True,
            )
        ]


def build_fourier_target(
    mission_contract: Any,
    chord_ref: Sequence[float],
    eta: Sequence[float],
    r3: float,
    r5: float,
) -> FourierTarget:
    """Build a mission-aware Fourier spanload target from normalized coordinates."""

    eta_array = _as_finite_array(eta, "eta")
    chord_array = _as_finite_array(chord_ref, "chord_ref")
    if eta_array.size != chord_array.size:
        raise ValueError("eta and chord_ref must have the same length.")
    if eta_array.size < 2:
        raise ValueError("At least two eta stations are required.")
    if np.any(np.diff(eta_array) < -1.0e-12):
        raise ValueError("eta must be sorted from root to tip.")
    if float(eta_array[0]) < -1.0e-12 or float(eta_array[-1]) > 1.0 + 1.0e-12:
        raise ValueError("eta must stay within [0, 1].")
    if np.any(chord_array <= 0.0):
        raise ValueError("chord_ref values must be positive.")

    eta_array = np.clip(eta_array, 0.0, 1.0)
    span_m = _positive_contract_float(mission_contract, "span_m")
    speed_mps = _positive_contract_float(mission_contract, "speed_mps")
    rho = _positive_contract_float(mission_contract, "rho")
    weight_n = _positive_contract_float(mission_contract, "weight_n")
    cl_req = _positive_contract_float(mission_contract, "CL_req")
    aspect_ratio = _positive_contract_float(mission_contract, "aspect_ratio")

    theta = np.arccos(eta_array)
    a1 = float(cl_req / (pi * aspect_ratio))
    r3_value = _finite_float(r3, "r3")
    r5_value = _finite_float(r5, "r5")
    harmonic_shape = (
        np.sin(theta)
        + r3_value * np.sin(3.0 * theta)
        + r5_value * np.sin(5.0 * theta)
    )
    gamma = 2.0 * span_m * speed_mps * a1 * harmonic_shape
    lprime = rho * speed_mps * gamma
    cl_target = 2.0 * gamma / (speed_mps * chord_array)
    if not np.all(np.isfinite(cl_target)):
        raise ValueError("cl_target must be finite.")

    y = 0.5 * span_m * eta_array
    lift_total_n = 2.0 * _trapz(lprime, y)
    lift_error_n = float(lift_total_n - weight_n)
    lift_error_fraction = float(lift_error_n / max(abs(weight_n), 1.0e-12))
    e_theory = float(1.0 / (1.0 + 3.0 * r3_value**2 + 5.0 * r5_value**2))
    if not isfinite(e_theory) or e_theory <= 0.0:
        raise ValueError("e_theory must be positive and finite.")

    baseline_gamma = 2.0 * span_m * speed_mps * a1 * np.sin(theta)
    baseline_lprime = rho * speed_mps * baseline_gamma
    outer_lift_fraction = _fraction_above_eta(eta_array, lprime, DEFAULT_OUTER_ETA_MIN)
    baseline_outer_lift_fraction = _fraction_above_eta(
        eta_array,
        baseline_lprime,
        DEFAULT_OUTER_ETA_MIN,
    )
    outer_lift_ratio_vs_ellipse = float(
        outer_lift_fraction / max(baseline_outer_lift_fraction, 1.0e-12)
    )
    root_bending_proxy = _trapz(lprime * y, y)

    warnings = _validation_warnings(
        gamma=gamma,
        cl_target=cl_target,
        lift_error_fraction=lift_error_fraction,
        e_theory=e_theory,
    )
    return FourierTarget(
        y=_tuple_float(y),
        eta=_tuple_float(eta_array),
        theta=_tuple_float(theta),
        chord_ref=_tuple_float(chord_array),
        gamma_target=_tuple_float(gamma),
        lprime_target=_tuple_float(lprime),
        cl_target=_tuple_float(cl_target),
        A1=float(a1),
        r3=float(r3_value),
        r5=float(r5_value),
        e_theory=float(e_theory),
        CL_req=float(cl_req),
        AR=float(aspect_ratio),
        outer_lift_fraction=float(outer_lift_fraction),
        outer_lift_ratio_vs_ellipse=float(outer_lift_ratio_vs_ellipse),
        root_bending_proxy=float(root_bending_proxy),
        gamma_min=float(np.min(gamma)),
        cl_max=float(np.max(cl_target)),
        source=FOURIER_TARGET_SOURCE,
        lift_total_n=float(lift_total_n),
        lift_error_n=float(lift_error_n),
        lift_error_fraction=float(lift_error_fraction),
        validation_status="warning" if warnings else "ok",
        validation_warnings=tuple(warnings),
    )


def compare_fourier_target_to_avl(
    target: FourierTarget,
    station_table: Sequence[Mapping[str, Any]],
    *,
    outer_eta_min: float = DEFAULT_OUTER_ETA_MIN,
) -> dict[str, Any]:
    """Compare AVL actual loading to a Fourier target as normalized half-span shapes."""

    target_eta = np.asarray(target.eta, dtype=float)
    target_loading = np.asarray(target.lprime_target, dtype=float)
    avl_eta, avl_loading = _avl_loading_arrays(station_table)
    if target_eta.size < 2 or avl_eta.size < 2:
        return _empty_comparison("insufficient_loading_points")

    order = np.argsort(avl_eta)
    avl_eta = avl_eta[order]
    avl_loading = avl_loading[order]
    unique_eta, unique_indices = np.unique(avl_eta, return_index=True)
    avl_eta = unique_eta
    avl_loading = avl_loading[unique_indices]
    if avl_eta.size < 2:
        return _empty_comparison("insufficient_unique_avl_eta")

    avl_on_target = np.interp(target_eta, avl_eta, avl_loading)
    target_norm = _normalized_distribution(target_eta, target_loading)
    avl_norm = _normalized_distribution(target_eta, avl_on_target)
    if target_norm is None or avl_norm is None:
        return _empty_comparison("invalid_loading_integral")

    delta = target_norm - avl_norm
    finite_mask = np.isfinite(delta)
    if not np.any(finite_mask):
        return _empty_comparison("nonfinite_loading_delta")
    delta = delta[finite_mask]
    eta_for_delta = target_eta[finite_mask]
    outer_mask = eta_for_delta >= float(outer_eta_min)
    outer_delta = delta[outer_mask] if np.any(outer_mask) else delta
    return {
        "target_vs_avl_compare_success": True,
        "target_vs_avl_rms_delta": float(np.sqrt(np.mean(delta**2))),
        "target_vs_avl_max_delta": float(np.max(np.abs(delta))),
        "target_vs_avl_outer_delta": float(np.max(np.abs(outer_delta))),
        "target_vs_avl_compare_source": "normalized_half_span_lprime_shape",
        "target_vs_avl_outer_eta_min": float(outer_eta_min),
        "target_loading_integral": _trapz(target_loading, target_eta),
        "avl_loading_integral": _trapz(avl_on_target, target_eta),
    }


def _empty_comparison(reason: str) -> dict[str, Any]:
    return {
        "target_vs_avl_compare_success": False,
        "target_vs_avl_compare_reason": reason,
        "target_vs_avl_rms_delta": None,
        "target_vs_avl_max_delta": None,
        "target_vs_avl_outer_delta": None,
    }


def _avl_loading_arrays(
    station_table: Sequence[Mapping[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    etas: list[float] = []
    loadings: list[float] = []
    for row in station_table:
        eta = _optional_float(row.get("eta"))
        loading = _optional_float(row.get("avl_circulation_proxy"))
        if loading is None:
            avl_cl = _optional_float(row.get("avl_local_cl"))
            chord = _optional_float(row.get("chord_m"))
            if avl_cl is not None and chord is not None:
                loading = avl_cl * chord
        if eta is None or loading is None:
            continue
        if not (0.0 <= eta <= 1.0):
            continue
        etas.append(float(eta))
        loadings.append(float(max(loading, 0.0)))
    return np.asarray(etas, dtype=float), np.asarray(loadings, dtype=float)


def _normalized_distribution(eta: np.ndarray, values: np.ndarray) -> np.ndarray | None:
    clipped = np.maximum(np.asarray(values, dtype=float), 0.0)
    integral = _trapz(clipped, eta)
    if not isfinite(integral) or integral <= 1.0e-12:
        return None
    return clipped / integral


def _fraction_above_eta(eta: np.ndarray, values: np.ndarray, eta_min: float) -> float:
    total = _trapz(values, eta)
    if not isfinite(total) or total <= 1.0e-12:
        return 0.0
    eta_min_float = float(eta_min)
    if eta_min_float <= float(eta[0]):
        return 1.0
    if eta_min_float >= float(eta[-1]):
        return 0.0
    eta_outer = eta[eta > eta_min_float]
    values_outer = values[eta > eta_min_float]
    eta_with_cut = np.concatenate(([eta_min_float], eta_outer))
    values_with_cut = np.concatenate(([np.interp(eta_min_float, eta, values)], values_outer))
    return float(_trapz(values_with_cut, eta_with_cut) / total)


def _validation_warnings(
    *,
    gamma: np.ndarray,
    cl_target: np.ndarray,
    lift_error_fraction: float,
    e_theory: float,
) -> list[str]:
    warnings: list[str] = []
    max_gamma = float(np.max(np.abs(gamma))) if gamma.size else 0.0
    if float(np.min(gamma)) < -1.0e-6 * max(max_gamma, 1.0):
        warnings.append("gamma_target_meaningfully_negative")
    if not np.all(np.isfinite(cl_target)):
        warnings.append("cl_target_nonfinite")
    if abs(float(lift_error_fraction)) > 0.02:
        warnings.append("lift_reconstruction_error_above_2_percent")
    if e_theory < 0.50 or e_theory > 1.000001:
        warnings.append("e_theory_outside_nominal_range")
    return warnings


def _positive_contract_float(contract: Any, field_name: str) -> float:
    value: Any
    if isinstance(contract, Mapping):
        value = contract.get(field_name)
    else:
        value = getattr(contract, field_name)
    parsed = _finite_float(value, field_name)
    if parsed <= 0.0:
        raise ValueError(f"{field_name} must be > 0.")
    return parsed


def _as_finite_array(values: Sequence[float], field_name: str) -> np.ndarray:
    array = np.asarray(tuple(values), dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{field_name} must be a one-dimensional sequence.")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{field_name} must contain only finite values.")
    return array


def _finite_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite.") from exc
    if not isfinite(parsed):
        raise ValueError(f"{field_name} must be finite.")
    return parsed


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _tuple_float(values: np.ndarray) -> tuple[float, ...]:
    return tuple(float(value) for value in values)


def _trapz(values: np.ndarray, x: np.ndarray) -> float:
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(values, x))
    return float(np.trapz(values, x))
