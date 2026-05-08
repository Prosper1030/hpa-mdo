"""Fourier-AVL spanload calibration diagnostics for pipeline v2 MVP 1.

This module is intentionally report-only. It fits existing AVL actual spanload
rows into low-order Fourier coefficients and writes traceable artifacts without
changing ranking, gates, optimizers, or structural truth labels.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

LOW_ORDER_HARMONICS: tuple[int, ...] = (1, 3, 5, 7)
DEFAULT_OUTER_ETA_MIN = 0.70
SCHEMA_VERSION = "fourier_avl_calibration_mvp_v1"


@dataclass(frozen=True)
class FourierAvlCalibrationCase:
    case_id: str
    station_rows: Sequence[Mapping[str, Any]]
    span_m: float | None = None
    speed_mps: float | None = None
    rho_kg_m3: float | None = None
    e_avl_cdi: float | None = None
    cdi_avl: float | None = None
    commanded_r3: float | None = None
    commanded_r5: float | None = None
    commanded_r7: float | None = None
    source_artifact: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class FourierAvlCalibrationResult:
    case_id: str
    fit_row: dict[str, Any]
    bridge_row: dict[str, Any]
    engineering_notes: tuple[str, ...]


def fit_case_to_fourier_bridge(
    case: FourierAvlCalibrationCase,
    *,
    outer_eta_min: float = DEFAULT_OUTER_ETA_MIN,
) -> FourierAvlCalibrationResult:
    """Fit one AVL actual spanload case and build a command-vs-realized bridge row."""

    speed_mps = _positive_or_none(case.speed_mps)
    eta, y, _chord, target_loading, avl_loading, target_source, avl_source = (
        _station_calibration_arrays(
            case.station_rows,
            span_m=case.span_m,
            speed_mps=speed_mps,
            rho_kg_m3=_positive_or_none(case.rho_kg_m3),
        )
    )
    span_m = _positive_or_infer(case.span_m, "span_m", fallback=2.0 * float(np.max(y)))

    avl_fit = _fit_loading_to_fourier(
        eta=eta,
        loading=avl_loading,
        span_m=span_m,
        speed_mps=speed_mps,
        loading_source=avl_source,
    )
    target_fit = _fit_loading_to_fourier(
        eta=eta,
        loading=target_loading,
        span_m=span_m,
        speed_mps=speed_mps,
        loading_source=target_source,
    )

    target_norm = _normalized_distribution(eta, target_loading)
    avl_norm = _normalized_distribution(eta, avl_loading)
    if target_norm is None or avl_norm is None:
        raise ValueError(f"Case {case.case_id} has invalid target or AVL loading integral.")
    delta = target_norm - avl_norm
    outer_mask = eta >= float(outer_eta_min)
    outer_delta = delta[outer_mask] if np.any(outer_mask) else delta
    target_outer = _fraction_above_eta(eta, target_loading, outer_eta_min)
    avl_outer = _fraction_above_eta(eta, avl_loading, outer_eta_min)
    target_bending = _bending_proxy(y, target_loading)
    avl_bending = _bending_proxy(y, avl_loading)
    quality_flags = _quality_flags(
        station_count=int(eta.size),
        target_source=target_source,
        avl_source=avl_source,
        target_loading=target_loading,
        avl_loading=avl_loading,
        avl_fit=avl_fit,
    )

    commanded_r3 = _coalesce_float(case.commanded_r3, target_fit["r3"])
    commanded_r5 = _coalesce_float(case.commanded_r5, target_fit["r5"])
    commanded_r7 = _coalesce_float(case.commanded_r7, target_fit["r7"])
    e_fourier_command = _fourier_efficiency(commanded_r3, commanded_r5, commanded_r7)

    metrics = {
        "target_vs_avl_rms": float(np.sqrt(np.mean(delta**2))),
        "target_vs_avl_max_delta": float(np.max(np.abs(delta))),
        "target_vs_avl_outer_delta": float(np.max(np.abs(outer_delta))),
        "outer_lift_fraction_command": float(target_outer),
        "outer_lift_fraction_avl": float(avl_outer),
        "bending_proxy_command_m": float(target_bending),
        "bending_proxy_avl_m": float(avl_bending),
        "bending_proxy_delta_m": float(avl_bending - target_bending),
    }
    status, notes = _diagnose_bridge_status(
        metrics=metrics,
        e_fourier_command=e_fourier_command,
        e_fourier_realized=float(avl_fit["e_fourier_fit"]),
        e_avl_cdi=case.e_avl_cdi,
        quality_flags=quality_flags,
    )

    fit_row = {
        "schema_version": SCHEMA_VERSION,
        "case_id": str(case.case_id),
        "source_artifact": case.source_artifact or "",
        "source_report": _note_value(case.notes, "source_report"),
        "station_count": int(eta.size),
        "span_m": float(span_m),
        "speed_mps": "" if speed_mps is None else float(speed_mps),
        "theta_convention": "theta_rad = acos(eta), root=pi/2, tip=0",
        "target_loading_source": target_source,
        "loading_source": avl_source,
        "coefficient_basis": avl_fit["coefficient_basis"],
        "A1": avl_fit["A1"],
        "A3": avl_fit["A3"],
        "A5": avl_fit["A5"],
        "A7": avl_fit["A7"],
        "r3": avl_fit["r3"],
        "r5": avl_fit["r5"],
        "r7": avl_fit["r7"],
        "e_fourier_fit": avl_fit["e_fourier_fit"],
        "e_avl_cdi": "" if case.e_avl_cdi is None else float(case.e_avl_cdi),
        "cdi_avl": "" if case.cdi_avl is None else float(case.cdi_avl),
        "fit_residual_rms": avl_fit["fit_residual_rms"],
        "fit_condition_number": avl_fit["fit_condition_number"],
        "target_negative_loading_count": int(np.sum(target_loading < 0.0)),
        "avl_negative_loading_count": int(np.sum(avl_loading < 0.0)),
        "target_vs_avl_rms": metrics["target_vs_avl_rms"],
        "target_vs_avl_outer_delta": metrics["target_vs_avl_outer_delta"],
        "bending_proxy_avl_m": metrics["bending_proxy_avl_m"],
        "bridge_status": status,
        "quality_flags": "; ".join(quality_flags),
    }
    bridge_row = {
        "schema_version": SCHEMA_VERSION,
        "case_id": str(case.case_id),
        "source_artifact": case.source_artifact or "",
        "source_report": _note_value(case.notes, "source_report"),
        "target_loading_source": target_source,
        "avl_loading_source": avl_source,
        "commanded_r3": commanded_r3,
        "commanded_r5": commanded_r5,
        "commanded_r7": commanded_r7,
        "realized_r3": avl_fit["r3"],
        "realized_r5": avl_fit["r5"],
        "realized_r7": avl_fit["r7"],
        "delta_r3": float(avl_fit["r3"] - commanded_r3),
        "delta_r5": float(avl_fit["r5"] - commanded_r5),
        "delta_r7": float(avl_fit["r7"] - commanded_r7),
        "e_fourier_command": float(e_fourier_command),
        "e_fourier_realized": avl_fit["e_fourier_fit"],
        "e_avl_realized": "" if case.e_avl_cdi is None else float(case.e_avl_cdi),
        "target_vs_avl_rms": metrics["target_vs_avl_rms"],
        "target_vs_avl_max_delta": metrics["target_vs_avl_max_delta"],
        "target_vs_avl_outer_delta": metrics["target_vs_avl_outer_delta"],
        "outer_lift_fraction_command": metrics["outer_lift_fraction_command"],
        "outer_lift_fraction_avl": metrics["outer_lift_fraction_avl"],
        "bending_proxy_command_m": metrics["bending_proxy_command_m"],
        "bending_proxy_avl_m": metrics["bending_proxy_avl_m"],
        "bending_proxy_delta_m": metrics["bending_proxy_delta_m"],
        "bridge_status": status,
        "mismatch_diagnosis": "; ".join(notes),
        "quality_flags": "; ".join(quality_flags),
    }
    return FourierAvlCalibrationResult(
        case_id=str(case.case_id),
        fit_row=fit_row,
        bridge_row=bridge_row,
        engineering_notes=tuple(notes),
    )


def write_fourier_avl_calibration_artifacts(
    cases: Sequence[FourierAvlCalibrationCase],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write the five required MVP 1 artifacts for a list of calibration cases."""

    if not cases:
        raise ValueError("At least one calibration case is required.")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    results = [fit_case_to_fourier_bridge(case) for case in cases]

    paths = {
        "spanload_definition": output_path / "spanload_definition.md",
        "avl_to_fourier_fit": output_path / "avl_to_fourier_fit.csv",
        "fourier_command_to_avl_realized": output_path
        / "fourier_command_to_avl_realized.csv",
        "fourier_avl_calibration_report": output_path / "fourier_avl_calibration_report.md",
        "recommended_fourier_bridge": output_path / "recommended_fourier_bridge.md",
    }
    paths["spanload_definition"].write_text(_spanload_definition_markdown(), encoding="utf-8")
    _write_csv(paths["avl_to_fourier_fit"], [result.fit_row for result in results])
    _write_csv(
        paths["fourier_command_to_avl_realized"],
        [result.bridge_row for result in results],
    )
    paths["fourier_avl_calibration_report"].write_text(
        _calibration_report_markdown(results),
        encoding="utf-8",
    )
    paths["recommended_fourier_bridge"].write_text(
        _recommended_bridge_markdown(results),
        encoding="utf-8",
    )
    return paths


def _station_calibration_arrays(
    rows: Sequence[Mapping[str, Any]],
    *,
    span_m: float | None,
    speed_mps: float | None,
    rho_kg_m3: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, str, str]:
    entries: list[tuple[float, float, float, float, float, str, str]] = []
    effective_span_m = span_m
    if effective_span_m is None:
        y_candidates = [
            value
            for value in (_optional_float(row.get("y_m")) for row in rows)
            if value is not None and value >= 0.0
        ]
        if y_candidates:
            effective_span_m = 2.0 * max(y_candidates)
    for row in rows:
        eta = _optional_float(row.get("eta"))
        y = _optional_float(row.get("y_m"))
        chord = _optional_float(row.get("chord_m"))
        target_loading, target_source = _target_loading_from_row(
            row,
            speed_mps=speed_mps,
            rho_kg_m3=rho_kg_m3,
        )
        avl_loading, avl_source = _avl_loading_from_row(
            row,
            speed_mps=speed_mps,
            rho_kg_m3=rho_kg_m3,
        )
        if eta is None and y is not None and effective_span_m is not None and effective_span_m > 0.0:
            eta = y / (0.5 * effective_span_m)
        if eta is None or not (0.0 <= eta <= 1.0):
            continue
        if target_loading is None or avl_loading is None:
            continue
        if y is None:
            if effective_span_m is None or effective_span_m <= 0.0:
                y = eta
            else:
                y = 0.5 * effective_span_m * eta
        if chord is None:
            chord = 1.0
        entries.append(
            (
                float(eta),
                float(y),
                float(chord),
                float(target_loading),
                float(avl_loading),
                target_source,
                avl_source,
            )
        )
    if len(entries) < 4:
        raise ValueError(
            "At least four finite stations with target and AVL loading are required for "
            "A1/A3/A5/A7 fitting."
        )
    entries.sort(key=lambda item: item[0])
    unique_entries: list[tuple[float, float, float, float, float, str, str]] = []
    seen_eta: set[float] = set()
    for entry in entries:
        eta_key = round(entry[0], 12)
        if eta_key in seen_eta:
            continue
        seen_eta.add(eta_key)
        unique_entries.append(entry)
    if len(unique_entries) < 4:
        raise ValueError("At least four unique eta stations are required for A1/A3/A5/A7 fitting.")
    eta, y, chord, target, avl, target_sources, avl_sources = zip(*unique_entries, strict=True)
    return (
        np.asarray(eta, dtype=float),
        np.asarray(y, dtype=float),
        np.asarray(chord, dtype=float),
        np.asarray(target, dtype=float),
        np.asarray(avl, dtype=float),
        _dominant_source(target_sources),
        _dominant_source(avl_sources),
    )


def _target_loading_from_row(
    row: Mapping[str, Any],
    *,
    speed_mps: float | None,
    rho_kg_m3: float | None,
) -> tuple[float | None, str]:
    for key in (
        "target_circulation",
        "target_circulation_proxy",
        "gamma_target",
        "target_gamma",
        "Gamma_target_m2ps",
    ):
        value = _optional_float(row.get(key))
        if value is not None:
            return value, "target_gamma_m2ps"
    for key in ("target_Lprime_Npm", "lprime_target", "Lprime_target_Npm"):
        value = _optional_float(row.get(key))
        if value is not None:
            if speed_mps is not None and rho_kg_m3 is not None:
                return value / (rho_kg_m3 * speed_mps), "target_lprime_converted_to_gamma"
            return value, "target_lprime_Npm_shape_only"
    target_cl = _optional_float(row.get("target_cl"))
    chord = _optional_float(row.get("chord_m"))
    if target_cl is not None and chord is not None:
        cl_times_chord = target_cl * chord
        if speed_mps is not None:
            return 0.5 * speed_mps * cl_times_chord, "target_cl_times_chord_converted_to_gamma"
        return cl_times_chord, "target_cl_times_chord_shape_only"
    return None, ""


def _avl_loading_from_row(
    row: Mapping[str, Any],
    *,
    speed_mps: float | None,
    rho_kg_m3: float | None,
) -> tuple[float | None, str]:
    for key in ("Gamma_m2ps", "Gamma_avl_m2ps"):
        value = _optional_float(row.get(key))
        if value is not None:
            return value, "avl_gamma_m2ps"
    for key in ("avl_circulation", "avl_circulation_proxy"):
        value = _optional_float(row.get(key))
        if value is not None:
            if speed_mps is not None:
                return 0.5 * speed_mps * value, "legacy_avl_cl_times_chord_converted_to_gamma"
            return value, "legacy_avl_cl_times_chord_shape_only"
    for key in ("Lprime_Npm", "avl_Lprime_Npm", "lift_per_span_Npm", "lift_per_span"):
        value = _optional_float(row.get(key))
        if value is not None:
            if speed_mps is not None and rho_kg_m3 is not None:
                return value / (rho_kg_m3 * speed_mps), "avl_lprime_converted_to_gamma"
            return value, "avl_lprime_Npm_shape_only"
    avl_cl = _optional_float(row.get("avl_cl"))
    if avl_cl is None:
        avl_cl = _optional_float(row.get("avl_local_cl"))
    chord = _optional_float(row.get("chord_m"))
    if avl_cl is not None and chord is not None:
        cl_times_chord = avl_cl * chord
        if speed_mps is not None:
            return 0.5 * speed_mps * cl_times_chord, "avl_cl_times_chord_converted_to_gamma"
        return cl_times_chord, "avl_cl_times_chord_shape_only"
    return None, ""


def _dominant_source(values: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return max(counts, key=counts.get)


def _fit_loading_to_fourier(
    *,
    eta: np.ndarray,
    loading: np.ndarray,
    span_m: float,
    speed_mps: float | None,
    loading_source: str,
) -> dict[str, Any]:
    if eta.size != loading.size:
        raise ValueError("eta and loading arrays must have the same length.")
    theta = np.arccos(np.clip(eta, 0.0, 1.0))
    scale = 1.0
    basis_name = f"{loading_source}_shape_coefficients"
    if _is_gamma_like_source(loading_source) and speed_mps is not None and speed_mps > 0.0:
        scale = 2.0 * float(span_m) * float(speed_mps)
        basis_name = "Gamma_m2ps = 2 * span_m * V_mps * sum(A_n sin(n theta))"
    basis = np.column_stack([scale * np.sin(order * theta) for order in LOW_ORDER_HARMONICS])
    condition_number = float(np.linalg.cond(basis))
    coefficients, *_ = np.linalg.lstsq(basis, loading, rcond=None)
    reconstructed = basis @ coefficients
    residual = loading - reconstructed
    max_loading = float(np.max(np.abs(loading))) if loading.size else 1.0
    residual_rms = float(np.sqrt(np.mean(residual**2)) / max(max_loading, 1.0e-12))
    a1, a3, a5, a7 = (float(value) for value in coefficients)
    r3 = _ratio(a3, a1)
    r5 = _ratio(a5, a1)
    r7 = _ratio(a7, a1)
    return {
        "A1": a1,
        "A3": a3,
        "A5": a5,
        "A7": a7,
        "r3": r3,
        "r5": r5,
        "r7": r7,
        "e_fourier_fit": _fourier_efficiency(r3, r5, r7),
        "fit_residual_rms": residual_rms,
        "fit_condition_number": condition_number,
        "coefficient_basis": basis_name,
    }


def _is_gamma_like_source(source: str) -> bool:
    return (
        "gamma_m2ps" in source
        or source.endswith("_converted_to_gamma")
        or "_converted_to_gamma" in source
    )


def _quality_flags(
    *,
    station_count: int,
    target_source: str,
    avl_source: str,
    target_loading: np.ndarray,
    avl_loading: np.ndarray,
    avl_fit: Mapping[str, Any],
) -> tuple[str, ...]:
    flags: list[str] = []
    if int(station_count) < 12:
        flags.append("sparse_station_count_for_four_harmonic_fit")
    if _optional_float(avl_fit.get("fit_condition_number")) is not None and float(
        avl_fit["fit_condition_number"]
    ) > 1.0e6:
        flags.append("ill_conditioned_fourier_fit")
    if np.any(np.asarray(target_loading, dtype=float) < 0.0):
        flags.append("negative_target_loading_present")
    if np.any(np.asarray(avl_loading, dtype=float) < 0.0):
        flags.append("negative_avl_loading_present")
    if not _is_gamma_like_source(target_source):
        flags.append("target_loading_not_gamma_units")
    elif "_converted_to_gamma" in target_source:
        flags.append(f"{target_source}_unit_conversion")
    if not _is_gamma_like_source(avl_source):
        flags.append("avl_loading_not_gamma_units")
    elif "_converted_to_gamma" in avl_source:
        flags.append(f"{avl_source}_unit_conversion")
    return tuple(flags)


def _diagnose_bridge_status(
    *,
    metrics: Mapping[str, float],
    e_fourier_command: float,
    e_fourier_realized: float,
    e_avl_cdi: float | None,
    quality_flags: Sequence[str],
) -> tuple[str, tuple[str, ...]]:
    rms = float(metrics["target_vs_avl_rms"])
    outer_delta = float(metrics["target_vs_avl_outer_delta"])
    command_outer = float(metrics["outer_lift_fraction_command"])
    avl_outer = float(metrics["outer_lift_fraction_avl"])
    outer_ratio = avl_outer / max(command_outer, 1.0e-12)
    notes: list[str] = []
    if "target_loading_not_gamma_units" in quality_flags or "avl_loading_not_gamma_units" in quality_flags:
        notes.append("loading units are not fully converted to the documented Gamma convention")
        return "definition_mismatch", tuple(notes)
    if any("unit_conversion" in flag for flag in quality_flags):
        notes.append("legacy station-table loading units were converted to Gamma before fitting")
    if "sparse_station_count_for_four_harmonic_fit" in quality_flags:
        notes.append("fit uses a sparse station table; treat coefficient magnitudes as diagnostic")
    if "negative_target_loading_present" in quality_flags or "negative_avl_loading_present" in quality_flags:
        notes.append("negative loading is preserved in the Fourier fit and clipped only for fraction metrics")
    if rms <= 0.05 and outer_delta <= 0.08:
        notes.append("target and AVL normalized spanload shapes are closely aligned")
        if e_avl_cdi is not None and abs(float(e_avl_cdi) - float(e_fourier_realized)) > 0.12:
            notes.append("AVL e_CDi differs from fitted Fourier e; inspect AVL setup/reference drag")
            return "avl_setup_reference_suspect", tuple(notes)
        return "calibrated", tuple(notes)
    if outer_ratio < 0.85:
        notes.append(
            "AVL actual loading is weaker than commanded loading in the outer span; "
            "current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, "
            "loaded-dihedral, and AVL setup without additional case metadata"
        )
        if e_fourier_command - e_fourier_realized > 0.05:
            notes.append("realized Fourier efficiency is below commanded Fourier efficiency")
        if e_avl_cdi is not None and e_fourier_realized - float(e_avl_cdi) > 0.10:
            notes.append("AVL induced efficiency is lower than equivalent realized Fourier shape")
        return "outer_underloaded_authority_limited", tuple(notes)
    if outer_ratio > 1.15:
        notes.append(
            "AVL actual loading is stronger than commanded loading in the outer span; "
            "classify separately from outer-underload authority limits"
        )
        return "outer_overloaded_realization_mismatch", tuple(notes)
    if outer_delta > 0.10:
        notes.append("spanload shape mismatch is measured but is not dominantly outer underload or overload")
        return "spanload_shape_mismatch", tuple(notes)
    notes.append("spanload mismatch is measured but not uniquely classified by MVP 1 metrics")
    return "calibrated_with_mismatch", tuple(notes)


def _spanload_definition_markdown() -> str:
    return "\n".join(
        [
            "# Spanload Definition",
            "",
            "- `y_m`: half-wing spanwise coordinate in meters, root to tip.",
            "- `eta`: normalized half-span coordinate, `eta = y_m / (span_m / 2)`, root 0 and tip 1.",
            "- `theta_rad`: lifting-line coordinate `theta = acos(eta)`, root `pi/2` and tip 0.",
            "- `Lprime_Npm`: local lift per unit span from AVL or derived strip loading.",
            "- `cl_times_c`: local section `Cl * chord_m`, used only as a shape proxy when circulation is unavailable.",
            "- `Gamma_m2ps`: circulation proxy. When available, the fit uses `Gamma = 2 * span_m * V * sum(A_n sin(n theta))`.",
            "- Legacy exported `avl_circulation` rows from `station_table.csv` are `Cl * chord_m`; MVP 1 converts them to `Gamma_m2ps` with `0.5 * V_mps * Cl * chord_m` before fitting.",
            "- `normalized_loading`: positive loading divided by its half-span integral for target-vs-AVL shape comparison.",
            "- Negative loading, if present, is preserved in Fourier coefficient fitting and clipped only for positive lift-fraction diagnostics.",
            "- Half-span convention: CSV rows are root-to-tip half-wing rows. Full-wing lift is twice the half-wing integral when needed.",
            "- Trust label: MVP 1 calibration is diagnostic only; it does not change production ranking, gates, optimizers, or structure truth.",
            "",
        ]
    )


def _calibration_report_markdown(results: Sequence[FourierAvlCalibrationResult]) -> str:
    lines = [
        "# Fourier-AVL Calibration Report",
        "",
        "- Schema: `fourier_avl_calibration_mvp_v1`",
        "- Scope: MVP 1 diagnostic bridge only.",
        "- Production ranking changed: no.",
        "- Hard gates added: no.",
        "- Broad CST/NSGA/FEM run: no.",
        "",
        "## Cases",
        "",
        "| case | status | r3 command | r3 AVL | e Fourier command | e Fourier AVL-fit | e AVL CDi | RMS | outer delta | quality flags |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        row = result.bridge_row
        lines.append(
            "| "
            f"{row['case_id']} | {row['bridge_status']} | "
            f"{_fmt(row['commanded_r3'])} | {_fmt(row['realized_r3'])} | "
            f"{_fmt(row['e_fourier_command'])} | {_fmt(row['e_fourier_realized'])} | "
            f"{_fmt(row['e_avl_realized'])} | {_fmt(row['target_vs_avl_rms'])} | "
            f"{_fmt(row['target_vs_avl_outer_delta'])} | {row['quality_flags']} |"
        )
    lines.extend(["", "## Engineering Read", ""])
    for result in results:
        lines.append(f"- `{result.case_id}`: {result.bridge_row['mismatch_diagnosis']}.")
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "This calibration can describe the current measured AVL spanload in Fourier language.",
            "It is not a design acceptance gate and should not be interpreted as final structural or airfoil truth.",
            "",
        ]
    )
    return "\n".join(lines)


def _recommended_bridge_markdown(results: Sequence[FourierAvlCalibrationResult]) -> str:
    statuses = [str(result.bridge_row["bridge_status"]) for result in results]
    if any(status == "definition_mismatch" for status in statuses):
        recommendation = (
            "Do not advance to MVP 2 yet. Resolve the definition-level mismatch before using Fourier "
            "as a structure-search language."
        )
    elif any(
        status
        in {
            "outer_underloaded_authority_limited",
            "outer_overloaded_realization_mismatch",
            "spanload_shape_mismatch",
            "calibrated_with_mismatch",
        }
        for status in statuses
    ):
        recommendation = (
            "Advance to MVP 2 only with the measured commanded-to-realized rows carried as bridge "
            "uncertainty. Do not use raw commanded Fourier coefficients as truth."
        )
    else:
        recommendation = (
            "MVP 1 bridge is calibrated for the sampled cases. MVP 2 may use these measured rows "
            "as the initial Fourier-to-AVL bridge."
        )
    lines = [
        "# Recommended Fourier Bridge",
        "",
        f"- Cases calibrated: {len(results)}",
        f"- Statuses: {', '.join(statuses)}",
        f"- Recommendation: {recommendation}",
        "",
        "## Bridge Policy",
        "",
        "- Use `fourier_command_to_avl_realized.csv` as an explicit measured table.",
        "- Treat Fourier theoretical `e` as a design-language diagnostic, not the induced-drag authority.",
        "- Treat AVL `e_CDi` and AVL actual spanload as the aerodynamic evidence for downstream structure-budgeted search.",
        "- If a result is ambiguous, carry the status label forward instead of forcing a design decision.",
        "",
    ]
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _note_value(notes: str | None, key: str) -> str:
    if not notes:
        return ""
    prefix = f"{key}="
    for item in str(notes).split(";"):
        stripped = item.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :]
    return ""


def _normalized_distribution(eta: np.ndarray, values: np.ndarray) -> np.ndarray | None:
    clipped = np.maximum(np.asarray(values, dtype=float), 0.0)
    integral = _trapz(clipped, eta)
    if not math.isfinite(integral) or integral <= 1.0e-12:
        return None
    return clipped / integral


def _fraction_above_eta(eta: np.ndarray, values: np.ndarray, eta_min: float) -> float:
    clipped = np.maximum(np.asarray(values, dtype=float), 0.0)
    total = _trapz(clipped, eta)
    if not math.isfinite(total) or total <= 1.0e-12:
        return 0.0
    eta_min_float = float(eta_min)
    if eta_min_float <= float(eta[0]):
        return 1.0
    if eta_min_float >= float(eta[-1]):
        return 0.0
    mask = eta > eta_min_float
    eta_outer = np.concatenate(([eta_min_float], eta[mask]))
    values_outer = np.concatenate(([np.interp(eta_min_float, eta, clipped)], clipped[mask]))
    return float(_trapz(values_outer, eta_outer) / total)


def _bending_proxy(y: np.ndarray, loading: np.ndarray) -> float:
    clipped = np.maximum(np.asarray(loading, dtype=float), 0.0)
    integral = _trapz(clipped, y)
    if not math.isfinite(integral) or integral <= 1.0e-12:
        return 0.0
    return float(_trapz((clipped / integral) * y, y))


def _fourier_efficiency(r3: float, r5: float, r7: float) -> float:
    return float(1.0 / (1.0 + 3.0 * float(r3) ** 2 + 5.0 * float(r5) ** 2 + 7.0 * float(r7) ** 2))


def _ratio(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) <= 1.0e-14:
        return 0.0
    return float(numerator / denominator)


def _positive_or_infer(value: float | None, field_name: str, *, fallback: float) -> float:
    parsed = _positive_or_none(value)
    if parsed is not None:
        return parsed
    if fallback <= 0.0 or not math.isfinite(fallback):
        raise ValueError(f"{field_name} must be positive or inferable.")
    return float(fallback)


def _positive_or_none(value: float | None) -> float | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    if parsed <= 0.0:
        return None
    return parsed


def _coalesce_float(primary: float | None, fallback: float) -> float:
    parsed = _optional_float(primary)
    return float(fallback if parsed is None else parsed)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _trapz(values: np.ndarray, x: np.ndarray) -> float:
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(values, x))
    return float(np.trapz(values, x))


def _fmt(value: Any) -> str:
    parsed = _optional_float(value)
    if parsed is None:
        return ""
    return f"{parsed:.6g}"


def _csv_value(value: Any) -> Any:
    parsed = _optional_float(value)
    if parsed is not None:
        return f"{parsed:.12g}"
    return "" if value is None else value


__all__ = [
    "FourierAvlCalibrationCase",
    "FourierAvlCalibrationResult",
    "fit_case_to_fourier_bridge",
    "write_fourier_avl_calibration_artifacts",
]
