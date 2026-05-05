"""Zone-level airfoil sidecar helpers for the Birdman concept route.

Phase 4 keeps airfoil selection diagnostic-only.  The helpers here build
zone envelopes from loaded-shape AVL local Cl/Re, query the manual airfoil
fixtures at zone work points, and generate a small capped set of zone-level
assignments for AVL reruns.  They intentionally do not perform
station-by-station greedy airfoil selection.
"""

from __future__ import annotations

from dataclasses import asdict
import math
from typing import Any, Mapping, Sequence

import numpy as np

from hpa_mdo.airfoils.database import (
    AirfoilDatabase,
    AirfoilQuery,
    ZoneAirfoilAssignment,
    ZoneEnvelope,
)
from hpa_mdo.concept.atmosphere import LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S


def build_zone_envelopes(
    *,
    loaded_avl_spanwise_result: Sequence[Mapping[str, Any]],
    chord_distribution: Sequence[Mapping[str, Any]],
    mission_contract: Any,
    fourier_target: Any,
    zone_definitions: Sequence[ZoneAirfoilAssignment],
    current_profile_drag_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[ZoneEnvelope, ...]:
    """Build zone envelopes from loaded-shape AVL station data.

    The Cl source is always AVL actual local Cl.  Fourier target Cl is only
    used for diagnostics such as target-vs-actual zone delta.
    """

    rows = [dict(row) for row in loaded_avl_spanwise_result if isinstance(row, Mapping)]
    chord_points = _chord_points(chord_distribution)
    profile_rows = [
        dict(row) for row in (current_profile_drag_rows or []) if isinstance(row, Mapping)
    ]
    envelopes: list[ZoneEnvelope] = []
    for zone in zone_definitions:
        zone_rows = [
            row
            for row in rows
            if _finite_float(row.get("eta")) is not None
            and zone.contains_eta(float(row["eta"]))
        ]
        eta_values = [_finite_float(row.get("eta")) for row in zone_rows]
        re_values = [
            _station_re(row, chord_points, mission_contract)
            for row in zone_rows
        ]
        cl_values = [_actual_avl_cl(row) for row in zone_rows]
        re_clean = [float(value) for value in re_values if value is not None]
        cl_clean = [float(value) for value in cl_values if value is not None]
        fourier_values = [
            _fourier_cl_at_eta(fourier_target, float(eta))
            for eta in eta_values
            if eta is not None
        ]
        fourier_clean = [float(value) for value in fourier_values if value is not None]
        zone_profile_rows = [
            row
            for row in profile_rows
            if _finite_float(row.get("eta")) is not None
            and zone.contains_eta(float(row["eta"]))
        ]
        stall_margins = [
            _finite_float(row.get("stall_margin_deg")) for row in zone_profile_rows
        ]
        profile_cds = [_finite_float(row.get("cd_profile")) for row in zone_profile_rows]
        stall_clean = [float(value) for value in stall_margins if value is not None]
        cd_clean = [float(value) for value in profile_cds if value is not None]
        max_avl = max(cl_clean) if cl_clean else None
        max_fourier = max(fourier_clean) if fourier_clean else None
        envelopes.append(
            ZoneEnvelope(
                zone_name=str(zone.zone_name),
                eta_min=float(zone.eta_min),
                eta_max=float(zone.eta_max),
                re_min=min(re_clean) if re_clean else None,
                re_max=max(re_clean) if re_clean else None,
                re_p50=_percentile(re_clean, 50.0),
                cl_min=min(cl_clean) if cl_clean else None,
                cl_max=max(cl_clean) if cl_clean else None,
                cl_p50=_percentile(cl_clean, 50.0),
                cl_p90=_percentile(cl_clean, 90.0),
                max_avl_actual_cl=max_avl,
                max_fourier_target_cl=max_fourier,
                target_vs_actual_cl_delta=(
                    None if max_avl is None or max_fourier is None else max_fourier - max_avl
                ),
                current_airfoil_id=str(zone.airfoil_id),
                current_stall_margin=min(stall_clean) if stall_clean else None,
                current_profile_cd_estimate=_mean(cd_clean),
                source="loaded_dihedral_avl",
            )
        )
    return tuple(envelopes)


def query_zone_airfoil_topk(
    envelopes: Sequence[ZoneEnvelope],
    airfoil_database: AirfoilDatabase,
    *,
    top_k: int = 2,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Rank airfoil records at zone-level work points.

    Results are one candidate list per zone.  No station indices or per-station
    picks are produced.
    """

    requested = max(0, int(top_k))
    if requested == 0:
        return {str(envelope.zone_name): tuple() for envelope in envelopes}
    ranked_by_zone: dict[str, tuple[dict[str, Any], ...]] = {}
    for envelope in envelopes:
        candidates: list[dict[str, Any]] = []
        work_points = _zone_work_points(envelope)
        for record in airfoil_database.records.values():
            candidate = _score_airfoil_for_zone(
                envelope=envelope,
                airfoil_id=str(record.airfoil_id),
                database=airfoil_database,
                work_points=work_points,
            )
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                not bool(item.get("rough_feasible", False)),
                float(item.get("score", float("inf"))),
                str(item.get("airfoil_id", "")),
            )
        )
        ranked_by_zone[str(envelope.zone_name)] = tuple(candidates[:requested])
    return ranked_by_zone


def generate_airfoil_sidecar_combinations(
    baseline_assignment: Sequence[ZoneAirfoilAssignment],
    topk_by_zone: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    available_airfoil_ids: Sequence[str] | None = None,
    max_airfoil_combinations: int = 8,
) -> tuple[tuple[ZoneAirfoilAssignment, ...], ...]:
    """Generate a small deterministic set of zone-level sidecar assignments."""

    max_count = max(0, int(max_airfoil_combinations))
    if max_count == 0:
        return tuple()
    baseline = tuple(baseline_assignment)
    available = (
        None
        if available_airfoil_ids is None
        else {str(airfoil_id) for airfoil_id in available_airfoil_ids}
    )
    combinations: list[tuple[ZoneAirfoilAssignment, ...]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()

    def add(assignments: Sequence[ZoneAirfoilAssignment]) -> None:
        if len(combinations) >= max_count:
            return
        normalized = tuple(assignments)
        if available is not None and any(
            assignment.airfoil_id not in available for assignment in normalized
        ):
            return
        signature = _assignment_signature(normalized)
        if signature in seen:
            return
        seen.add(signature)
        combinations.append(normalized)

    add(baseline)
    for airfoil_id in ("dae31", "dae11", "dae21", "dae41"):
        if len(combinations) >= max_count:
            break
        if airfoil_id == "dae31":
            add(_replace_assignment_ids(baseline, {"mid2": airfoil_id, "tip": airfoil_id}))
        elif airfoil_id == "dae11":
            add(_replace_assignment_ids(baseline, {"root": airfoil_id, "mid1": airfoil_id}))
        elif airfoil_id == "dae21":
            add(_replace_assignment_ids(baseline, {"mid1": airfoil_id, "mid2": airfoil_id}))
        elif airfoil_id == "dae41":
            add(_replace_assignment_ids(baseline, {"tip": airfoil_id}))

    for zone in baseline:
        if len(combinations) >= max_count:
            break
        for candidate in topk_by_zone.get(zone.zone_name, ()):
            airfoil_id = str(candidate.get("airfoil_id", ""))
            if not airfoil_id or airfoil_id == zone.airfoil_id:
                continue
            add(_replace_assignment_ids(baseline, {zone.zone_name: airfoil_id}))
            if len(combinations) >= max_count:
                break

    if len(combinations) < max_count:
        top_choice: dict[str, str] = {}
        for zone in baseline:
            for candidate in topk_by_zone.get(zone.zone_name, ()):
                airfoil_id = str(candidate.get("airfoil_id", ""))
                if airfoil_id and airfoil_id != zone.airfoil_id:
                    top_choice[zone.zone_name] = airfoil_id
                    break
        if top_choice:
            add(_replace_assignment_ids(baseline, top_choice))

    return tuple(combinations)


def zone_envelopes_to_rows(envelopes: Sequence[ZoneEnvelope]) -> list[dict[str, Any]]:
    return [envelope.to_dict() if hasattr(envelope, "to_dict") else asdict(envelope) for envelope in envelopes]


def assignment_to_dicts(
    assignments: Sequence[ZoneAirfoilAssignment],
) -> list[dict[str, Any]]:
    return [assignment.to_dict() for assignment in assignments]


def assignment_label(assignments: Sequence[ZoneAirfoilAssignment]) -> str:
    return "|".join(
        f"{assignment.zone_name}:{assignment.airfoil_id}" for assignment in assignments
    )


def _score_airfoil_for_zone(
    *,
    envelope: ZoneEnvelope,
    airfoil_id: str,
    database: AirfoilDatabase,
    work_points: Sequence[tuple[float, float, float]],
) -> dict[str, Any] | None:
    record = database.records.get(airfoil_id)
    if record is None:
        return None
    if not work_points:
        return None
    cd_values: list[float] = []
    cm_values: list[float] = []
    stall_margins: list[float] = []
    clmax_margins: list[float] = []
    warnings: list[str] = []
    weighted_cd_sum = 0.0
    weight_sum = 0.0
    for re_value, cl_value, weight in work_points:
        result = database.lookup(
            AirfoilQuery(
                airfoil_id=airfoil_id,
                Re=float(re_value),
                cl=float(cl_value),
                allow_extrapolation=False,
            )
        )
        cd_values.append(float(result.cd))
        cm_values.append(float(result.cm))
        stall_margins.append(float(result.stall_margin_deg))
        clmax_margins.append(float(result.clmax_margin))
        warnings.extend(str(warning) for warning in result.warnings)
        weighted_cd_sum += float(weight) * float(result.cd)
        weight_sum += float(weight)
    rough_feasible = True
    if envelope.cl_max is not None:
        rough_feasible = float(envelope.cl_max) <= float(record.usable_clmax) + 1.0e-9
    min_stall = min(stall_margins) if stall_margins else None
    min_clmax = min(clmax_margins) if clmax_margins else None
    warning_count = len(set(warnings))
    mean_cd = weighted_cd_sum / max(weight_sum, 1.0e-12)
    source_quality = _sidecar_source_quality(record.source_quality, warning_count)
    score = float(mean_cd)
    if "not_mission_grade" in source_quality:
        score += 0.010
    score += 0.0015 * warning_count
    score += 0.0020 * abs(_mean(cm_values) or 0.0)
    if min_stall is not None:
        score += 0.0005 * max(0.0, 3.0 - float(min_stall))
    if min_clmax is not None:
        score += 0.0100 * max(0.0, -float(min_clmax))
    if not rough_feasible:
        score += 1.0
    return {
        "zone_name": str(envelope.zone_name),
        "airfoil_id": str(airfoil_id),
        "score": float(score),
        "mean_cd": float(mean_cd),
        "min_stall_margin_deg": min_stall,
        "min_clmax_margin": min_clmax,
        "cm_mean": _mean(cm_values),
        "alpha_L0_deg": float(record.alpha_L0_deg),
        "rough_feasible": bool(rough_feasible),
        "source_quality": source_quality,
        "warning_count": int(warning_count),
        "warnings": sorted(set(warnings)),
        "work_point_count": len(work_points),
    }


def _sidecar_source_quality(source_quality: str, warning_count: int) -> str:
    quality = str(source_quality)
    if (
        "mission_grade" in quality
        and "not_mission_grade" not in quality
        and warning_count == 0
    ):
        return "mission_grade_sidecar"
    return "not_mission_grade_sidecar"


def _zone_work_points(envelope: ZoneEnvelope) -> tuple[tuple[float, float, float], ...]:
    re_mid = _first_finite(envelope.re_p50, envelope.re_min, envelope.re_max)
    cl_mid = _first_finite(envelope.cl_p50, envelope.cl_min, envelope.cl_max)
    if re_mid is None or cl_mid is None:
        return tuple()
    points: list[tuple[float, float, float]] = [(float(re_mid), float(cl_mid), 1.0)]
    cl_p90 = _first_finite(envelope.cl_p90, envelope.cl_max, cl_mid)
    points.append((float(re_mid), float(cl_p90), 1.4))
    re_min = _first_finite(envelope.re_min, re_mid)
    cl_max = _first_finite(envelope.cl_max, cl_p90)
    points.append((float(re_min), float(cl_max), 1.2))
    re_max = _first_finite(envelope.re_max, re_mid)
    cl_min = _first_finite(envelope.cl_min, cl_mid)
    points.append((float(re_max), float(cl_min), 0.5))
    return tuple(points)


def _replace_assignment_ids(
    assignments: Sequence[ZoneAirfoilAssignment],
    replacements: Mapping[str, str],
) -> tuple[ZoneAirfoilAssignment, ...]:
    return tuple(
        ZoneAirfoilAssignment(
            zone_name=assignment.zone_name,
            airfoil_id=str(replacements.get(assignment.zone_name, assignment.airfoil_id)),
            eta_min=float(assignment.eta_min),
            eta_max=float(assignment.eta_max),
            source="zone_airfoil_sidecar_shadow_v1",
        )
        for assignment in assignments
    )


def _assignment_signature(
    assignments: Sequence[ZoneAirfoilAssignment],
) -> tuple[tuple[str, str], ...]:
    return tuple((assignment.zone_name, assignment.airfoil_id) for assignment in assignments)


def _station_re(
    row: Mapping[str, Any],
    chord_points: Sequence[tuple[float, float, float]],
    mission_contract: Any,
) -> float | None:
    for key in ("Re", "reynolds", "avl_reynolds"):
        value = _finite_float(row.get(key))
        if value is not None and value > 0.0:
            return float(value)
    chord = _finite_float(row.get("chord_m", row.get("chord")))
    if chord is None:
        eta = _finite_float(row.get("eta"))
        y_m = _finite_float(row.get("y_m", row.get("y")))
        if eta is not None or y_m is not None:
            chord = _interpolate_chord(eta=eta, y_m=y_m, chord_points=chord_points)
    if chord is None or chord <= 0.0:
        return None
    speed = _contract_float(mission_contract, "speed_mps")
    rho = _contract_float(mission_contract, "rho")
    mu = _contract_float(
        mission_contract,
        "dynamic_viscosity_pa_s",
        default=LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S,
    )
    if speed is None or rho is None or mu is None or mu <= 0.0:
        return None
    return float(rho * speed * chord / mu)


def _actual_avl_cl(row: Mapping[str, Any]) -> float | None:
    for key in ("cl_actual_avl", "avl_local_cl", "avl_cl"):
        value = _finite_float(row.get(key))
        if value is not None:
            return float(value)
    return None


def _fourier_cl_at_eta(fourier_target: Any, eta: float) -> float | None:
    if fourier_target is None:
        return None
    target_eta = getattr(fourier_target, "eta", None)
    target_cl = getattr(fourier_target, "cl_target", None)
    if isinstance(fourier_target, Mapping):
        target_eta = fourier_target.get("eta")
        target_cl = fourier_target.get("cl_target")
    if not isinstance(target_eta, Sequence) or not isinstance(target_cl, Sequence):
        return None
    eta_values = [_finite_float(value) for value in target_eta]
    cl_values = [_finite_float(value) for value in target_cl]
    pairs = [
        (float(eta_value), float(cl_value))
        for eta_value, cl_value in zip(eta_values, cl_values, strict=False)
        if eta_value is not None and cl_value is not None
    ]
    if not pairs:
        return None
    pairs.sort(key=lambda item: item[0])
    xs = np.asarray([pair[0] for pair in pairs], dtype=float)
    ys = np.asarray([pair[1] for pair in pairs], dtype=float)
    return float(np.interp(float(eta), xs, ys))


def _chord_points(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for row in rows:
        chord = _finite_float(row.get("chord_m", row.get("chord")))
        y_m = _finite_float(row.get("y_m", row.get("y")))
        eta = _finite_float(row.get("eta"))
        if chord is None or chord <= 0.0:
            continue
        if eta is None and y_m is None:
            continue
        points.append(
            (
                float(eta if eta is not None else y_m),
                float(y_m if y_m is not None else eta),
                float(chord),
            )
        )
    return tuple(sorted(points, key=lambda item: item[1]))


def _interpolate_chord(
    *,
    eta: float | None,
    y_m: float | None,
    chord_points: Sequence[tuple[float, float, float]],
) -> float | None:
    if not chord_points:
        return None
    if eta is not None:
        xs = np.asarray([point[0] for point in chord_points], dtype=float)
        chords = np.asarray([point[2] for point in chord_points], dtype=float)
        return float(np.interp(float(eta), xs, chords))
    if y_m is not None:
        ys = np.asarray([point[1] for point in chord_points], dtype=float)
        chords = np.asarray([point[2] for point in chord_points], dtype=float)
        return float(np.interp(float(y_m), ys, chords))
    return None


def _contract_float(contract: Any, field: str, default: float | None = None) -> float | None:
    value = getattr(contract, field, None)
    if value is None and isinstance(contract, Mapping):
        value = contract.get(field)
    parsed = _finite_float(value)
    return float(parsed) if parsed is not None else default


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    return None


def _first_finite(*values: float | None) -> float | None:
    for value in values:
        parsed = _finite_float(value)
        if parsed is not None:
            return float(parsed)
    return None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return float(np.percentile(np.asarray(clean, dtype=float), float(percentile)))


def _mean(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return float(sum(clean) / len(clean))
