"""Airfoil polar database fixtures and shadow profile-drag integration.

Phase 3 intentionally provides a formal interface and auditable manual
fixtures.  It does not run CST/XFOIL, choose station-by-station airfoils, or
promote placeholder polar data to mission grade.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from functools import lru_cache
from math import isfinite, pi
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from hpa_mdo.concept.atmosphere import LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S


_REPO_ROOT = Path(__file__).resolve().parents[3]
_FX76_POLAR_CSV = _REPO_ROOT / "docs" / "research" / "xfoil_fx76mp140_re410000" / "fx76mp140_re410000.csv"


@dataclass(frozen=True)
class AirfoilPolarPoint:
    Re: float
    cl: float
    cd: float
    cm: float
    alpha_deg: float
    roughness_mode: str = "clean"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AirfoilRecord:
    airfoil_id: str
    name: str
    source: str
    source_quality: str
    zone_hint: str
    thickness_ratio: float
    max_camber: float
    alpha_L0_deg: float
    cl_alpha_per_rad: float
    cm_design: float
    safe_clmax: float
    usable_clmax: float
    polar_points: tuple[AirfoilPolarPoint, ...]
    notes: str

    @property
    def polar_table(self) -> tuple[AirfoilPolarPoint, ...]:
        return self.polar_points

    def to_dict(self, *, include_polar_points: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if include_polar_points:
            payload["polar_points"] = [point.to_dict() for point in self.polar_points]
        else:
            payload["polar_points"] = {"count": len(self.polar_points)}
        payload["polar_table"] = payload["polar_points"]
        return payload


@dataclass(frozen=True)
class AirfoilQuery:
    airfoil_id: str
    Re: float
    cl: float
    roughness_mode: str | None = None
    allow_extrapolation: bool = False


@dataclass(frozen=True)
class AirfoilQueryResult:
    cd: float
    cm: float
    alpha_deg: float
    stall_margin_deg: float
    clmax_margin: float
    interpolated: bool
    extrapolated: bool
    source_quality: str
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ZoneEnvelope:
    zone_name: str
    eta_min: float
    eta_max: float
    re_min: float | None = None
    re_max: float | None = None
    re_p50: float | None = None
    cl_min: float | None = None
    cl_max: float | None = None
    cl_p50: float | None = None
    cl_p90: float | None = None
    max_avl_actual_cl: float | None = None
    max_fourier_target_cl: float | None = None
    target_vs_actual_cl_delta: float | None = None
    current_airfoil_id: str | None = None
    current_stall_margin: float | None = None
    current_profile_cd_estimate: float | None = None
    source: str = "loaded_dihedral_avl"

    def contains_eta(self, eta: float) -> bool:
        eta_float = float(eta)
        if self.zone_name == "tip":
            return self.eta_min <= eta_float <= self.eta_max
        return self.eta_min <= eta_float < self.eta_max

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ZoneAirfoilAssignment:
    zone_name: str
    airfoil_id: str
    eta_min: float
    eta_max: float
    source: str = "fixed_seed_airfoil_zone_assignment_shadow"

    def envelope(self) -> ZoneEnvelope:
        return ZoneEnvelope(
            zone_name=self.zone_name,
            eta_min=float(self.eta_min),
            eta_max=float(self.eta_max),
        )

    def contains_eta(self, eta: float) -> bool:
        return self.envelope().contains_eta(eta)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileDragIntegrationResult:
    CD_profile: float
    station_rows: tuple[dict[str, Any], ...]
    source_quality: str
    station_warning_count: int
    min_stall_margin_deg: float | None
    max_station_cl_utilization: float | None
    cd0_total_est: float
    drag_budget_band: str
    zone_airfoil_assignment: tuple[ZoneAirfoilAssignment, ...]
    profile_drag_cl_source_shape_mode: str = "flat_or_unverified_loaded_shape"
    profile_drag_cl_source_loaded_shape: bool = False
    profile_drag_cl_source_warning_count: int = 1
    source: str = "airfoil_database_profile_drag_shadow_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "CD_profile": float(self.CD_profile),
            "profile_cd_airfoil_db": float(self.CD_profile),
            "station_rows": [dict(row) for row in self.station_rows],
            "source_quality": self.source_quality,
            "station_warning_count": int(self.station_warning_count),
            "min_stall_margin_deg": self.min_stall_margin_deg,
            "max_station_cl_utilization": self.max_station_cl_utilization,
            "cd0_total_est": float(self.cd0_total_est),
            "cd0_total_est_airfoil_db": float(self.cd0_total_est),
            "drag_budget_band": self.drag_budget_band,
            "mission_drag_budget_band_airfoil_db": self.drag_budget_band,
            "profile_drag_cl_source_shape_mode": self.profile_drag_cl_source_shape_mode,
            "profile_drag_cl_source_loaded_shape": bool(
                self.profile_drag_cl_source_loaded_shape
            ),
            "profile_drag_cl_source_warning_count": int(
                self.profile_drag_cl_source_warning_count
            ),
            "zone_airfoil_assignment": [
                assignment.to_dict() for assignment in self.zone_airfoil_assignment
            ],
        }


class AirfoilDatabase:
    def __init__(self, records: Mapping[str, AirfoilRecord]):
        self.records = dict(records)

    @classmethod
    def from_records(cls, records: Sequence[AirfoilRecord]) -> "AirfoilDatabase":
        return cls({record.airfoil_id: record for record in records})

    def lookup(self, query: AirfoilQuery) -> AirfoilQueryResult:
        record = self.records.get(str(query.airfoil_id))
        if record is None:
            raise KeyError(f"Unknown airfoil_id: {query.airfoil_id}")
        return _lookup_record(record, query)


def lookup_airfoil_polar(
    airfoil_id: str,
    Re: float,
    cl: float,
    *,
    roughness_mode: str | None = None,
    allow_extrapolation: bool = False,
    airfoil_database: AirfoilDatabase | None = None,
) -> AirfoilQueryResult:
    database = default_airfoil_database() if airfoil_database is None else airfoil_database
    return database.lookup(
        AirfoilQuery(
            airfoil_id=str(airfoil_id),
            Re=float(Re),
            cl=float(cl),
            roughness_mode=roughness_mode,
            allow_extrapolation=bool(allow_extrapolation),
        )
    )


def fixed_seed_zone_airfoil_assignments() -> tuple[ZoneAirfoilAssignment, ...]:
    return (
        ZoneAirfoilAssignment("root", "fx76mp140", 0.00, 0.25),
        ZoneAirfoilAssignment("mid1", "fx76mp140", 0.25, 0.55),
        ZoneAirfoilAssignment("mid2", "clarkysm", 0.55, 0.80),
        ZoneAirfoilAssignment("tip", "clarkysm", 0.80, 1.00),
    )


def integrate_profile_drag_from_avl(
    mission_contract: Any,
    avl_spanwise_result: Sequence[Mapping[str, Any]],
    chord_distribution: Sequence[Mapping[str, Any]],
    zone_airfoil_assignment: Sequence[ZoneAirfoilAssignment] | Mapping[str, str],
    airfoil_database: AirfoilDatabase,
    *,
    cl_source_shape_mode: str = "flat_or_unverified_loaded_shape",
    cl_source_loaded_shape: bool | None = None,
    cl_source_warning_count: int | None = None,
) -> ProfileDragIntegrationResult:
    """Integrate wing profile drag using AVL actual local Cl."""

    source_shape_mode = str(cl_source_shape_mode or "flat_or_unverified_loaded_shape")
    source_loaded_shape = (
        source_shape_mode == "loaded_dihedral_avl"
        if cl_source_loaded_shape is None
        else bool(cl_source_loaded_shape)
    )
    if cl_source_warning_count is None:
        source_warning_count = 0 if source_loaded_shape else 1
    else:
        source_warning_count = max(0, int(cl_source_warning_count))
    if not source_loaded_shape and source_warning_count == 0:
        source_warning_count = 1

    speed_mps = _positive_contract_float(mission_contract, "speed_mps")
    rho = _positive_contract_float(mission_contract, "rho")
    wing_area_m2 = _positive_contract_float(mission_contract, "wing_area_m2")
    dynamic_viscosity = _contract_float(
        mission_contract,
        "dynamic_viscosity_pa_s",
        default=LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S,
    )
    if dynamic_viscosity <= 0.0:
        raise ValueError("dynamic_viscosity_pa_s must be positive.")

    assignments = _normalize_assignments(zone_airfoil_assignment)
    chord_points = _chord_points(chord_distribution)
    station_rows: list[dict[str, Any]] = []
    drag_area_points: list[tuple[float, float]] = []
    source_qualities: list[str] = []
    warning_count = 0
    stall_margins: list[float] = []
    cl_utils: list[float] = []

    for row in avl_spanwise_result:
        y_m = _required_float(row.get("y_m"), "y_m")
        eta = _optional_float(row.get("eta"))
        if eta is None:
            eta = y_m / max(0.5 * _positive_contract_float(mission_contract, "span_m"), 1.0e-12)
        eta = min(max(float(eta), 0.0), 1.0)
        chord = _optional_float(row.get("chord_m"))
        if chord is None:
            chord = _interpolate_chord(eta=eta, y_m=y_m, chord_points=chord_points)
        if chord is None or chord <= 0.0:
            raise ValueError("Each AVL station must provide or map to a positive chord.")
        cl_actual = _actual_avl_cl(row)
        airfoil_id = _airfoil_id_for_eta(assignments, eta)
        reynolds = rho * speed_mps * float(chord) / dynamic_viscosity
        query = airfoil_database.lookup(
            AirfoilQuery(
                airfoil_id=airfoil_id,
                Re=float(reynolds),
                cl=float(cl_actual),
                allow_extrapolation=False,
            )
        )
        record = airfoil_database.records[airfoil_id]
        cl_util = abs(float(cl_actual)) / max(float(record.safe_clmax), 1.0e-12)
        warnings = tuple(query.warnings)
        warning_count += len(warnings)
        source_qualities.append(query.source_quality)
        stall_margins.append(float(query.stall_margin_deg))
        cl_utils.append(float(cl_util))
        local_drag_area = float(chord) * float(query.cd)
        drag_area_points.append((float(y_m), local_drag_area))
        station_rows.append(
            {
                "eta": float(eta),
                "y": float(y_m),
                "y_m": float(y_m),
                "chord": float(chord),
                "chord_m": float(chord),
                "Re": float(reynolds),
                "cl_actual_avl": float(cl_actual),
                "airfoil_id": str(airfoil_id),
                "cd_profile": float(query.cd),
                "cm": float(query.cm),
                "alpha_deg": float(query.alpha_deg),
                "stall_margin_deg": float(query.stall_margin_deg),
                "clmax_margin": float(query.clmax_margin),
                "cl_utilization": float(cl_util),
                "source_quality": str(query.source_quality),
                "warning_flags": list(warnings),
                "profile_drag_cl_source_shape_mode": source_shape_mode,
                "profile_drag_cl_source_loaded_shape": bool(source_loaded_shape),
            }
        )

    if len(drag_area_points) < 2:
        raise ValueError("At least two AVL stations are required for profile drag integration.")
    drag_area_points.sort(key=lambda item: item[0])
    y_values = np.asarray([point[0] for point in drag_area_points], dtype=float)
    drag_area_values = np.asarray([point[1] for point in drag_area_points], dtype=float)
    cd_profile = float(2.0 * _trapz(drag_area_values, y_values) / wing_area_m2)
    cd0_total_est = cd_profile + _contract_float(
        mission_contract,
        "CDA_nonwing_target_m2",
        default=0.0,
    ) / wing_area_m2
    return ProfileDragIntegrationResult(
        CD_profile=cd_profile,
        station_rows=tuple(station_rows),
        source_quality=_aggregate_source_quality(source_qualities),
        station_warning_count=int(warning_count),
        min_stall_margin_deg=min(stall_margins) if stall_margins else None,
        max_station_cl_utilization=max(cl_utils) if cl_utils else None,
        cd0_total_est=float(cd0_total_est),
        drag_budget_band=_classify_drag_budget_band(mission_contract, cd_profile, cd0_total_est),
        zone_airfoil_assignment=assignments,
        profile_drag_cl_source_shape_mode=source_shape_mode,
        profile_drag_cl_source_loaded_shape=bool(source_loaded_shape),
        profile_drag_cl_source_warning_count=int(source_warning_count),
    )


@lru_cache(maxsize=1)
def default_airfoil_database() -> AirfoilDatabase:
    return AirfoilDatabase.from_records(
        (
            _fx76_record(),
            _clarky_record(),
            _placeholder_record(
                airfoil_id="dae31",
                name="DAE31",
                zone_hint="tip",
                thickness_ratio=0.119,
                max_camber=0.035,
                alpha_l0_deg=-2.2,
                cl_alpha_per_rad=5.75,
                cm_design=-0.075,
                safe_clmax=1.20,
                usable_clmax=1.35,
            ),
            _placeholder_record(
                airfoil_id="dae11",
                name="DAE11",
                zone_hint="root",
                thickness_ratio=0.142,
                max_camber=0.040,
                alpha_l0_deg=-2.6,
                cl_alpha_per_rad=5.80,
                cm_design=-0.090,
                safe_clmax=1.25,
                usable_clmax=1.40,
            ),
            _placeholder_record(
                airfoil_id="dae21",
                name="DAE21",
                zone_hint="mid",
                thickness_ratio=0.128,
                max_camber=0.037,
                alpha_l0_deg=-2.4,
                cl_alpha_per_rad=5.78,
                cm_design=-0.083,
                safe_clmax=1.23,
                usable_clmax=1.38,
            ),
            _placeholder_record(
                airfoil_id="dae41",
                name="DAE41",
                zone_hint="tip",
                thickness_ratio=0.105,
                max_camber=0.030,
                alpha_l0_deg=-2.0,
                cl_alpha_per_rad=5.70,
                cm_design=-0.065,
                safe_clmax=1.15,
                usable_clmax=1.30,
            ),
        )
    )


def _fx76_record() -> AirfoilRecord:
    points = _load_fx76_polar_points()
    return AirfoilRecord(
        airfoil_id="fx76mp140",
        name="FX 76-MP-140",
        source=str(_FX76_POLAR_CSV.relative_to(_REPO_ROOT)),
        source_quality="manual_xfoil_single_re_reference_not_mission_grade",
        zone_hint="root,mid1",
        thickness_ratio=0.14,
        max_camber=0.055,
        alpha_L0_deg=-3.6,
        cl_alpha_per_rad=5.85,
        cm_design=-0.19,
        safe_clmax=1.55,
        usable_clmax=1.68,
        polar_points=points,
        notes=(
            "Single-Re XFOIL reference fixture from docs/research; useful for "
            "shadow estimates only, not mission-grade polar coverage."
        ),
    )


def _clarky_record() -> AirfoilRecord:
    return AirfoilRecord(
        airfoil_id="clarkysm",
        name="ClarkY smoothed",
        source="manual_quadratic_fixture_from_seed_route",
        source_quality="manual_placeholder_not_mission_grade",
        zone_hint="mid2,tip",
        thickness_ratio=0.117,
        max_camber=0.035,
        alpha_L0_deg=-2.4,
        cl_alpha_per_rad=5.70,
        cm_design=-0.075,
        safe_clmax=1.25,
        usable_clmax=1.40,
        polar_points=_quadratic_polar_points(
            re_values=(180_000.0, 280_000.0, 410_000.0),
            cl_values=(-0.1, 0.2, 0.5, 0.8, 1.1, 1.3),
            cd0=0.0095,
            k=0.0095,
            cl_ref=0.65,
            cm=-0.075,
            alpha_l0=-2.4,
            cl_alpha=5.70,
        ),
        notes="Manual ClarkY smoothed fixture; no mission-grade XFOIL polar attached.",
    )


def _placeholder_record(
    *,
    airfoil_id: str,
    name: str,
    zone_hint: str,
    thickness_ratio: float,
    max_camber: float,
    alpha_l0_deg: float,
    cl_alpha_per_rad: float,
    cm_design: float,
    safe_clmax: float,
    usable_clmax: float,
) -> AirfoilRecord:
    return AirfoilRecord(
        airfoil_id=airfoil_id,
        name=name,
        source="historical_airfoil_geometry_placeholder_without_verified_polar",
        source_quality="manual_placeholder_not_mission_grade",
        zone_hint=zone_hint,
        thickness_ratio=float(thickness_ratio),
        max_camber=float(max_camber),
        alpha_L0_deg=float(alpha_l0_deg),
        cl_alpha_per_rad=float(cl_alpha_per_rad),
        cm_design=float(cm_design),
        safe_clmax=float(safe_clmax),
        usable_clmax=float(usable_clmax),
        polar_points=_quadratic_polar_points(
            re_values=(180_000.0, 280_000.0, 410_000.0),
            cl_values=(-0.1, 0.2, 0.5, 0.8, 1.1),
            cd0=0.0105,
            k=0.0120,
            cl_ref=0.65,
            cm=cm_design,
            alpha_l0=alpha_l0_deg,
            cl_alpha=cl_alpha_per_rad,
        ),
        notes=(
            "Placeholder DAE-family polar for schema completeness only; do not "
            "treat as mission-grade."
        ),
    )


def _load_fx76_polar_points() -> tuple[AirfoilPolarPoint, ...]:
    if not _FX76_POLAR_CSV.is_file():
        return _quadratic_polar_points(
            re_values=(410_000.0,),
            cl_values=(0.4, 0.7, 1.0, 1.3, 1.6),
            cd0=0.0108,
            k=0.0085,
            cl_ref=1.05,
            cm=-0.19,
            alpha_l0=-3.6,
            cl_alpha=5.85,
        )
    points: list[AirfoilPolarPoint] = []
    with _FX76_POLAR_CSV.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            points.append(
                AirfoilPolarPoint(
                    Re=410_000.0,
                    cl=float(row["cl"]),
                    cd=float(row["cd"]),
                    cm=float(row["cm"]),
                    alpha_deg=float(row["alpha"]),
                )
            )
    return tuple(points)


def _quadratic_polar_points(
    *,
    re_values: Sequence[float],
    cl_values: Sequence[float],
    cd0: float,
    k: float,
    cl_ref: float,
    cm: float,
    alpha_l0: float,
    cl_alpha: float,
) -> tuple[AirfoilPolarPoint, ...]:
    points: list[AirfoilPolarPoint] = []
    for re_value in re_values:
        re_correction = (max(re_values) / max(float(re_value), 1.0e-9)) ** 0.2
        for cl_value in cl_values:
            points.append(
                AirfoilPolarPoint(
                    Re=float(re_value),
                    cl=float(cl_value),
                    cd=float(cd0 * re_correction + float(k) * (float(cl_value) - cl_ref) ** 2),
                    cm=float(cm),
                    alpha_deg=float(alpha_l0 + (180.0 / pi) * float(cl_value) / cl_alpha),
                )
            )
    return tuple(points)


def _lookup_record(record: AirfoilRecord, query: AirfoilQuery) -> AirfoilQueryResult:
    if not record.polar_points:
        raise ValueError(f"Airfoil {record.airfoil_id} has no polar points.")
    re_values = sorted({float(point.Re) for point in record.polar_points})
    warnings: list[str] = []
    extrapolated = False
    re_low, re_high, re_outside = _bracket(
        re_values,
        float(query.Re),
        allow_extrapolation=bool(query.allow_extrapolation),
    )
    if re_outside:
        extrapolated = True
        warnings.append("re_outside_polar_envelope")

    low_values, low_interp, low_extra, low_warnings = _interpolate_at_re(
        record,
        re_low,
        float(query.cl),
        allow_extrapolation=bool(query.allow_extrapolation),
    )
    warnings.extend(low_warnings)
    extrapolated = extrapolated or low_extra
    if re_high == re_low:
        values = low_values
        interpolated = low_interp
    else:
        high_values, high_interp, high_extra, high_warnings = _interpolate_at_re(
            record,
            re_high,
            float(query.cl),
            allow_extrapolation=bool(query.allow_extrapolation),
        )
        warnings.extend(high_warnings)
        extrapolated = extrapolated or high_extra
        fraction = (float(query.Re) - re_low) / max(re_high - re_low, 1.0e-12)
        fraction = float(fraction if query.allow_extrapolation else min(max(fraction, 0.0), 1.0))
        values = {
            key: _lerp(float(low_values[key]), float(high_values[key]), fraction)
            for key in ("cd", "cm", "alpha_deg")
        }
        interpolated = True or low_interp or high_interp

    clmax_margin = float(record.safe_clmax - float(query.cl))
    stall_margin_deg = float((clmax_margin / max(record.cl_alpha_per_rad, 1.0e-12)) * 180.0 / pi)
    source_quality = str(record.source_quality)
    if warnings and "not_mission_grade" not in source_quality:
        source_quality = f"{source_quality}_query_warning_not_mission_grade"
    elif warnings and "query_warning" not in source_quality:
        source_quality = f"{source_quality}|query_warning_not_mission_grade"
    return AirfoilQueryResult(
        cd=float(values["cd"]),
        cm=float(values["cm"]),
        alpha_deg=float(values["alpha_deg"]),
        stall_margin_deg=stall_margin_deg,
        clmax_margin=clmax_margin,
        interpolated=bool(interpolated),
        extrapolated=bool(extrapolated),
        source_quality=source_quality,
        warnings=tuple(sorted(set(warnings))),
    )


def _interpolate_at_re(
    record: AirfoilRecord,
    re_value: float,
    cl: float,
    *,
    allow_extrapolation: bool,
) -> tuple[dict[str, float], bool, bool, list[str]]:
    points = sorted(
        (point for point in record.polar_points if abs(float(point.Re) - float(re_value)) <= 1.0e-9),
        key=lambda point: float(point.cl),
    )
    cl_values = [float(point.cl) for point in points]
    cl_low, cl_high, cl_outside = _bracket(
        cl_values,
        float(cl),
        allow_extrapolation=allow_extrapolation,
    )
    warnings = ["cl_outside_polar_envelope"] if cl_outside else []
    low = _point_for_cl(points, cl_low)
    high = _point_for_cl(points, cl_high)
    if cl_high == cl_low:
        return {
            "cd": float(low.cd),
            "cm": float(low.cm),
            "alpha_deg": float(low.alpha_deg),
        }, False, cl_outside, warnings
    fraction = (float(cl) - cl_low) / max(cl_high - cl_low, 1.0e-12)
    fraction = float(fraction if allow_extrapolation else min(max(fraction, 0.0), 1.0))
    return {
        "cd": _lerp(float(low.cd), float(high.cd), fraction),
        "cm": _lerp(float(low.cm), float(high.cm), fraction),
        "alpha_deg": _lerp(float(low.alpha_deg), float(high.alpha_deg), fraction),
    }, True, cl_outside, warnings


def _bracket(
    values: Sequence[float],
    query_value: float,
    *,
    allow_extrapolation: bool,
) -> tuple[float, float, bool]:
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        raise ValueError("Cannot bracket an empty value set.")
    if len(sorted_values) == 1:
        return sorted_values[0], sorted_values[0], not _close(query_value, sorted_values[0])
    if query_value <= sorted_values[0]:
        if _close(query_value, sorted_values[0]):
            return sorted_values[0], sorted_values[0], False
        return (
            (sorted_values[0], sorted_values[1], True)
            if allow_extrapolation
            else (sorted_values[0], sorted_values[0], True)
        )
    if query_value >= sorted_values[-1]:
        if _close(query_value, sorted_values[-1]):
            return sorted_values[-1], sorted_values[-1], False
        return (
            (sorted_values[-2], sorted_values[-1], True)
            if allow_extrapolation
            else (sorted_values[-1], sorted_values[-1], True)
        )
    for left, right in zip(sorted_values[:-1], sorted_values[1:], strict=True):
        if left <= query_value <= right:
            if _close(query_value, left):
                return left, left, False
            if _close(query_value, right):
                return right, right, False
            return left, right, False
    return sorted_values[-1], sorted_values[-1], True


def _point_for_cl(points: Sequence[AirfoilPolarPoint], cl: float) -> AirfoilPolarPoint:
    return min(points, key=lambda point: abs(float(point.cl) - float(cl)))


def _normalize_assignments(
    assignments: Sequence[ZoneAirfoilAssignment] | Mapping[str, str],
) -> tuple[ZoneAirfoilAssignment, ...]:
    if isinstance(assignments, Mapping):
        default_bounds = {
            "root": (0.00, 0.25),
            "mid1": (0.25, 0.55),
            "mid2": (0.55, 0.80),
            "tip": (0.80, 1.00),
        }
        return tuple(
            ZoneAirfoilAssignment(zone, airfoil_id, *default_bounds.get(zone, (0.0, 1.0)))
            for zone, airfoil_id in assignments.items()
        )
    return tuple(assignments)


def _airfoil_id_for_eta(assignments: tuple[ZoneAirfoilAssignment, ...], eta: float) -> str:
    for assignment in assignments:
        if assignment.contains_eta(float(eta)):
            return assignment.airfoil_id
    nearest = min(assignments, key=lambda item: min(abs(float(eta) - item.eta_min), abs(float(eta) - item.eta_max)))
    return nearest.airfoil_id


def _actual_avl_cl(row: Mapping[str, Any]) -> float:
    for key in ("cl_actual_avl", "avl_local_cl", "avl_cl"):
        value = _optional_float(row.get(key))
        if value is not None:
            return value
    raise ValueError("AVL actual local Cl is required; Fourier target Cl is not accepted.")


def _chord_points(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[float | None, float, float], ...]:
    points: list[tuple[float | None, float, float]] = []
    for row in rows:
        chord = _optional_float(row.get("chord_m", row.get("chord")))
        y_m = _optional_float(row.get("y_m", row.get("y")))
        eta = _optional_float(row.get("eta"))
        if chord is None or y_m is None or chord <= 0.0:
            continue
        points.append((eta, float(y_m), float(chord)))
    return tuple(sorted(points, key=lambda item: item[1]))


def _interpolate_chord(
    *,
    eta: float,
    y_m: float,
    chord_points: tuple[tuple[float | None, float, float], ...],
) -> float | None:
    if not chord_points:
        return None
    if all(point[0] is not None for point in chord_points):
        xs = np.asarray([float(point[0]) for point in chord_points], dtype=float)
        chords = np.asarray([point[2] for point in chord_points], dtype=float)
        return float(np.interp(float(eta), xs, chords))
    ys = np.asarray([point[1] for point in chord_points], dtype=float)
    chords = np.asarray([point[2] for point in chord_points], dtype=float)
    return float(np.interp(float(y_m), ys, chords))


def _classify_drag_budget_band(contract: Any, cd_profile: float, cd0_total_est: float) -> str:
    if (
        cd0_total_est <= _contract_float(contract, "CD0_total_target", default=float("inf"))
        and cd_profile <= _contract_float(contract, "CD_wing_profile_target", default=float("inf"))
    ):
        return "target"
    if (
        cd0_total_est <= _contract_float(contract, "CD0_total_boundary", default=float("inf"))
        and cd_profile <= _contract_float(contract, "CD_wing_profile_boundary", default=float("inf"))
    ):
        return "boundary"
    if cd0_total_est <= _contract_float(contract, "CD0_total_rescue", default=float("inf")):
        return "rescue"
    return "over_budget"


def _aggregate_source_quality(values: Sequence[str]) -> str:
    qualities = tuple(sorted(set(str(value) for value in values if value)))
    if not qualities:
        return "unknown_not_mission_grade"
    if len(qualities) == 1:
        return qualities[0]
    if any("not_mission_grade" in quality for quality in qualities):
        return "mixed_not_mission_grade:" + ",".join(qualities)
    return "mixed:" + ",".join(qualities)


def _contract_float(contract: Any, field_name: str, *, default: float) -> float:
    value: Any
    if isinstance(contract, Mapping):
        value = contract.get(field_name, default)
    else:
        value = getattr(contract, field_name, default)
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _positive_contract_float(contract: Any, field_name: str) -> float:
    value = _contract_float(contract, field_name, default=float("nan"))
    if not isfinite(value) or value <= 0.0:
        raise ValueError(f"{field_name} must be positive.")
    return value


def _required_float(value: Any, field_name: str) -> float:
    parsed = _optional_float(value)
    if parsed is None:
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


def _lerp(left: float, right: float, fraction: float) -> float:
    return float(left) + (float(right) - float(left)) * float(fraction)


def _close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= 1.0e-9


def _trapz(values: np.ndarray, x: np.ndarray) -> float:
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(values, x))
    return float(np.trapz(values, x))
