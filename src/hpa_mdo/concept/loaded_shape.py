"""Loaded cruise wing-shape shadow helpers for concept screening.

This module does not decide candidate acceptance.  It makes the assumed
loaded half-wing Z shape explicit so downstream AVL/profile-drag artifacts can
state whether their local Cl came from a flat or loaded-dihedral geometry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any, Sequence

from hpa_mdo.concept.geometry import WingStation


@dataclass(frozen=True)
class LoadedWingShape:
    eta: tuple[float, ...]
    y_m: tuple[float, ...]
    z_loaded_m: tuple[float, ...]
    loaded_dihedral_deg: tuple[float, ...]
    loaded_tip_z_m: float
    loaded_tip_dihedral_deg: float
    loaded_shape_mode: str
    source: str
    warnings: tuple[str, ...] = ()

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "eta": float(eta),
                "y_m": float(y),
                "z_loaded_m": float(z),
                "loaded_dihedral_deg": float(dihedral),
                "loaded_shape_mode": self.loaded_shape_mode,
                "source": self.source,
            }
            for eta, y, z, dihedral in zip(
                self.eta,
                self.y_m,
                self.z_loaded_m,
                self.loaded_dihedral_deg,
                strict=True,
            )
        ]


def build_loaded_wing_shape(
    *,
    span_m: float,
    eta: Sequence[float],
    loaded_tip_dihedral_deg: float,
    dihedral_exponent: float | None = None,
    loaded_shape_mode: str = "linear_dihedral",
    source: str = "loaded_wing_shape_shadow_v1",
) -> LoadedWingShape:
    """Build a simple half-span loaded Z shape from a tip dihedral angle."""

    span = float(span_m)
    if not math.isfinite(span) or span <= 0.0:
        raise ValueError("span_m must be positive.")
    eta_values = tuple(float(value) for value in eta)
    if not eta_values:
        raise ValueError("eta must not be empty.")
    if any(not math.isfinite(value) for value in eta_values):
        raise ValueError("eta values must be finite.")
    if any(value < -1.0e-9 or value > 1.0 + 1.0e-9 for value in eta_values):
        raise ValueError("eta values must stay in [0, 1].")

    exponent = 1.0 if dihedral_exponent is None else float(dihedral_exponent)
    if not math.isfinite(exponent) or exponent <= 0.0:
        raise ValueError("dihedral_exponent must be positive.")

    mode = str(loaded_shape_mode)
    if mode not in {"flat", "linear_dihedral", "concept_dihedral_fields"}:
        raise ValueError(f"Unsupported loaded_shape_mode: {loaded_shape_mode}")

    tip_dihedral = 0.0 if mode == "flat" else float(loaded_tip_dihedral_deg)
    if not math.isfinite(tip_dihedral):
        raise ValueError("loaded_tip_dihedral_deg must be finite.")

    half_span = 0.5 * span
    tan_tip = math.tan(math.radians(tip_dihedral))
    y_values = tuple(half_span * min(max(value, 0.0), 1.0) for value in eta_values)
    warnings: list[str] = []
    if mode != "flat" and abs(tip_dihedral) < 1.0e-9:
        warnings.append("zero_tip_dihedral_loaded_shape_is_flat")
    if tip_dihedral < 0.0:
        warnings.append("negative_loaded_tip_dihedral")

    z_values: list[float] = []
    dihedral_values: list[float] = []
    for eta_value in eta_values:
        eta_clamped = min(max(float(eta_value), 0.0), 1.0)
        if mode == "flat":
            z_values.append(0.0)
            dihedral_values.append(0.0)
            continue
        z_values.append(half_span * eta_clamped**exponent * tan_tip)
        if exponent == 1.0:
            local_slope = tan_tip
        elif eta_clamped <= 0.0:
            local_slope = 0.0 if exponent > 1.0 else tan_tip
        else:
            local_slope = exponent * eta_clamped ** (exponent - 1.0) * tan_tip
        dihedral_values.append(math.degrees(math.atan(local_slope)))

    if any(not math.isfinite(value) for value in z_values + dihedral_values):
        raise ValueError("Loaded wing shape produced non-finite values.")

    return LoadedWingShape(
        eta=eta_values,
        y_m=y_values,
        z_loaded_m=tuple(float(value) for value in z_values),
        loaded_dihedral_deg=tuple(float(value) for value in dihedral_values),
        loaded_tip_z_m=float(z_values[-1]),
        loaded_tip_dihedral_deg=float(tip_dihedral),
        loaded_shape_mode=mode,
        source=str(source),
        warnings=tuple(warnings),
    )


def build_loaded_wing_shape_from_stations(
    *,
    span_m: float,
    stations: Sequence[WingStation],
    loaded_shape_mode: str | None = None,
    source: str = "wing_station_dihedral_schedule_shadow",
) -> LoadedWingShape:
    """Reconstruct the loaded Z shape that the current AVL station list implies."""

    if not stations:
        raise ValueError("stations must not be empty.")
    half_span = 0.5 * float(span_m)
    eta_values = tuple(
        0.0 if half_span <= 0.0 else min(max(float(station.y_m) / half_span, 0.0), 1.0)
        for station in stations
    )
    explicit_z = tuple(getattr(station, "z_m", None) for station in stations)
    if any(value is not None for value in explicit_z):
        if any(value is None for value in explicit_z):
            raise ValueError("Either all stations or no stations must provide z_m.")
        z_values = tuple(float(value) for value in explicit_z if value is not None)
    else:
        z_accum = [0.0]
        for left, right in zip(stations[:-1], stations[1:]):
            dy_m = float(right.y_m) - float(left.y_m)
            mean_dihedral_rad = math.radians(
                0.5 * (float(left.dihedral_deg) + float(right.dihedral_deg))
            )
            z_accum.append(z_accum[-1] + dy_m * math.tan(mean_dihedral_rad))
        z_values = tuple(z_accum)

    max_abs_z = max((abs(value) for value in z_values), default=0.0)
    mode = (
        str(loaded_shape_mode)
        if loaded_shape_mode is not None
        else ("flat" if max_abs_z <= 1.0e-9 else "concept_dihedral_fields")
    )
    return LoadedWingShape(
        eta=eta_values,
        y_m=tuple(float(station.y_m) for station in stations),
        z_loaded_m=tuple(float(value) for value in z_values),
        loaded_dihedral_deg=tuple(float(station.dihedral_deg) for station in stations),
        loaded_tip_z_m=float(z_values[-1]),
        loaded_tip_dihedral_deg=float(stations[-1].dihedral_deg),
        loaded_shape_mode=mode,
        source=str(source),
        warnings=(),
    )


def apply_loaded_shape_to_stations(
    stations: Sequence[WingStation],
    loaded_shape: LoadedWingShape,
) -> tuple[WingStation, ...]:
    """Return stations with explicit loaded Z coordinates for AVL export."""

    station_tuple = tuple(stations)
    if len(station_tuple) != len(loaded_shape.z_loaded_m):
        raise ValueError("stations and loaded_shape must have the same length.")
    return tuple(
        replace(
            station,
            z_m=float(z_m),
            dihedral_deg=float(dihedral_deg),
        )
        for station, z_m, dihedral_deg in zip(
            station_tuple,
            loaded_shape.z_loaded_m,
            loaded_shape.loaded_dihedral_deg,
            strict=True,
        )
    )
