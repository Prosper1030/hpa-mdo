from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
if str(HPA_MESHING_SRC) not in sys.path:
    sys.path.insert(0, str(HPA_MESHING_SRC))

from hpa_meshing.mesh_native.blackcat import (  # noqa: E402
    _cosine_space_te_to_le,
    _distance_2d,
    _interp_z,
    _repair_lower_branch_above_upper,
    _resample_airfoil_loop,
)
from hpa_meshing.mesh_native.wing_surface import Reference, Station  # noqa: E402


CANDIDATE_ID = "current_avl_compromise_conservative_closed"
DEFAULT_GEOMETRY_DIR = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / CANDIDATE_ID
)
PIPELINE_FULL_SPAN_M = 34.332286
PIPELINE_HALF_SPAN_M = 17.166143


@dataclass(frozen=True)
class BaselineAuthority:
    geometry_dir: Path
    manifest_path: Path
    section_table_path: Path
    manifest: dict[str, Any]
    rows: tuple[dict[str, str], ...]
    half_stations: tuple[Station, ...]
    reference: Reference
    n_perim: int
    airfoil_loop_mode: str
    airfoil_geometry_reports: dict[str, dict[str, Any]]


def load_baseline_authority(
    *,
    n_perim: int,
    geometry_dir: Path | str = DEFAULT_GEOMETRY_DIR,
    airfoil_loop_mode: str = "legacy_resampled_loop",
    target_zero_te_gap_over_chord: float | None = None,
) -> BaselineAuthority:
    if n_perim < 16 or n_perim % 2:
        raise ValueError("n_perim must be an even integer >= 16")
    if airfoil_loop_mode not in {"legacy_resampled_loop", "open_te_cgrid"}:
        raise ValueError(f"unknown airfoil_loop_mode: {airfoil_loop_mode}")

    geometry_path = Path(geometry_dir)
    manifest_path = geometry_path / "geometry_manifest.json"
    section_table_path = geometry_path / "section_table.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = tuple(_read_csv_dicts(section_table_path))
    if not rows:
        raise ValueError(f"empty section table: {section_table_path}")

    reference = Reference(
        sref_full=_required_float(manifest, "Sref"),
        cref=_required_float(manifest, "Cref"),
        bref_full=_required_float(manifest, "Bref"),
    )
    half_span = _required_float(rows[-1], "y_m")
    _require_close("Bref", reference.bref_full, PIPELINE_FULL_SPAN_M, 1.0e-6)
    _require_close("section half span", half_span, PIPELINE_HALF_SPAN_M, 1.0e-6)

    points_per_side = n_perim // 2 + 1
    airfoil_cache: dict[str, list[tuple[float, float]]] = {}
    airfoil_geometry_reports: dict[str, dict[str, Any]] = {}
    stations: list[Station] = []
    for row in rows:
        dat_path = Path(row["airfoil_dat_path"])
        key = str(dat_path)
        airfoil_id = row.get("airfoil_id") or dat_path.stem
        loop = airfoil_cache.get(key)
        if loop is None:
            raw_points = _read_airfoil_dat(dat_path)
            if airfoil_loop_mode == "open_te_cgrid":
                loop, report = _resample_airfoil_open_te_cgrid(
                    raw_points,
                    points_per_side=points_per_side,
                    airfoil_id=airfoil_id,
                    target_zero_te_gap_over_chord=target_zero_te_gap_over_chord,
                )
                expected_count = n_perim + 1
            else:
                loop = _resample_airfoil_loop(
                    raw_points,
                    points_per_side=points_per_side,
                )
                report = _airfoil_geometry_report(
                    raw_points,
                    loop,
                    airfoil_id=airfoil_id,
                    airfoil_loop_mode=airfoil_loop_mode,
                    te_perturbation={
                        "introduced": False,
                        "reason": "legacy loop mode",
                        "gap_over_chord": 0.0,
                        "max_allowed_gap_over_chord": 0.0,
                    },
                )
                expected_count = n_perim
            if len(loop) != expected_count:
                raise ValueError(f"airfoil resampling count mismatch for {dat_path}")
            airfoil_cache[key] = loop
            airfoil_geometry_reports[airfoil_id] = report
        stations.append(
            Station(
                y=_required_float(row, "y_m"),
                x_le=_required_float(row, "x_le_m", default=0.0),
                z_le=_required_float(row, "z_m"),
                chord=_required_float(row, "chord_m"),
                twist_deg=_required_float(row, "twist_deg"),
                airfoil_xz=loop,
            )
        )

    return BaselineAuthority(
        geometry_dir=geometry_path,
        manifest_path=manifest_path,
        section_table_path=section_table_path,
        manifest=manifest,
        rows=rows,
        half_stations=tuple(stations),
        reference=reference,
        n_perim=n_perim,
        airfoil_loop_mode=airfoil_loop_mode,
        airfoil_geometry_reports=airfoil_geometry_reports,
    )


def build_adaptive_full_span_stations(
    authority: BaselineAuthority,
    *,
    twist_target_deg: float = 0.25,
    chord_ratio_target: float = 0.03,
    z_step_target_m: float = 0.08,
    morph_step_target: float = 0.08,
) -> tuple[list[Station], dict[str, Any]]:
    half = _adaptive_half_stations(
        authority.half_stations,
        twist_target_deg=twist_target_deg,
        chord_ratio_target=chord_ratio_target,
        z_step_target_m=z_step_target_m,
        morph_step_target=morph_step_target,
    )
    mirrored = [
        Station(
            y=-station.y,
            x_le=station.x_le,
            z_le=station.z_le,
            chord=station.chord,
            twist_deg=station.twist_deg,
            airfoil_xz=station.airfoil_xz,
        )
        for station in reversed(half[1:])
    ]
    full = [*mirrored, *half]
    report = geometry_change_report(full)
    report.update(
        {
            "authority_station_count_half": len(authority.half_stations),
            "adaptive_station_count_half": len(half),
            "adaptive_station_count_full": len(full),
            "span_cells_full": len(full) - 1,
            "thresholds": {
                "twist_target_deg": twist_target_deg,
                "chord_ratio_target": chord_ratio_target,
                "z_step_target_m": z_step_target_m,
                "morph_step_target": morph_step_target,
            },
        }
    )
    return full, report


def geometry_change_report(stations: Sequence[Station]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(stations[:-1], stations[1:])):
        rows.append(_bay_change_row(index, left, right))
    return {
        "bay_count": len(rows),
        "max_abs_twist_delta_deg": max(
            (abs(float(row["twist_delta_deg"])) for row in rows),
            default=0.0,
        ),
        "max_chord_ratio_delta": max(
            (abs(float(row["chord_ratio_delta"])) for row in rows),
            default=0.0,
        ),
        "max_abs_z_delta_m": max(
            (abs(float(row["z_delta_m"])) for row in rows),
            default=0.0,
        ),
        "max_airfoil_morph_step": max(
            (float(row["airfoil_morph_step"]) for row in rows),
            default=0.0,
        ),
        "max_section_surface_move_m": max(
            (float(row["max_section_surface_move_m"]) for row in rows),
            default=0.0,
        ),
        "rows": rows,
    }


def write_station_table(path: Path, stations: Sequence[Station]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "station_index",
                "y_m",
                "z_le_m",
                "x_le_m",
                "chord_m",
                "twist_deg",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for index, station in enumerate(stations):
            writer.writerow(
                {
                    "station_index": index,
                    "y_m": f"{station.y:.9f}",
                    "z_le_m": f"{station.z_le:.9f}",
                    "x_le_m": f"{station.x_le:.9f}",
                    "chord_m": f"{station.chord:.9f}",
                    "twist_deg": f"{station.twist_deg:.9f}",
                }
            )


def write_bay_change_table(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=list(rows[0].keys()),
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def interpolate_station(left: Station, right: Station, eta: float) -> Station:
    if len(left.airfoil_xz) != len(right.airfoil_xz):
        raise ValueError("Cannot interpolate stations with different airfoil point counts")
    return Station(
        y=_lerp(left.y, right.y, eta),
        x_le=_lerp(left.x_le, right.x_le, eta),
        z_le=_lerp(left.z_le, right.z_le, eta),
        chord=_lerp(left.chord, right.chord, eta),
        twist_deg=_lerp(left.twist_deg, right.twist_deg, eta),
        airfoil_xz=[
            (_lerp(a[0], b[0], eta), _lerp(a[1], b[1], eta))
            for a, b in zip(left.airfoil_xz, right.airfoil_xz)
        ],
    )


def _adaptive_half_stations(
    stations: Sequence[Station],
    *,
    twist_target_deg: float,
    chord_ratio_target: float,
    z_step_target_m: float,
    morph_step_target: float,
) -> list[Station]:
    refined: list[Station] = []
    for left, right in zip(stations[:-1], stations[1:]):
        if not refined:
            refined.append(left)
        steps = _required_bay_subdivisions(
            left,
            right,
            twist_target_deg=twist_target_deg,
            chord_ratio_target=chord_ratio_target,
            z_step_target_m=z_step_target_m,
            morph_step_target=morph_step_target,
        )
        for step in range(1, steps + 1):
            refined.append(interpolate_station(left, right, step / steps))
    return refined


def _required_bay_subdivisions(
    left: Station,
    right: Station,
    *,
    twist_target_deg: float,
    chord_ratio_target: float,
    z_step_target_m: float,
    morph_step_target: float,
) -> int:
    twist_steps = math.ceil(abs(right.twist_deg - left.twist_deg) / twist_target_deg)
    chord_delta = abs(right.chord - left.chord) / max(min(left.chord, right.chord), 1.0e-12)
    chord_steps = math.ceil(chord_delta / chord_ratio_target)
    z_steps = math.ceil(abs(right.z_le - left.z_le) / z_step_target_m)
    morph_steps = math.ceil(_airfoil_morph_step(left, right) / morph_step_target)
    return max(1, twist_steps, chord_steps, z_steps, morph_steps)


def _bay_change_row(index: int, left: Station, right: Station) -> dict[str, Any]:
    return {
        "bay_index": index,
        "y_left_m": f"{left.y:.9f}",
        "y_right_m": f"{right.y:.9f}",
        "dy_m": f"{right.y - left.y:.9f}",
        "twist_delta_deg": f"{right.twist_deg - left.twist_deg:.9f}",
        "chord_ratio_delta": f"{right.chord / left.chord - 1.0:.9f}",
        "z_delta_m": f"{right.z_le - left.z_le:.9f}",
        "airfoil_morph_step": f"{_airfoil_morph_step(left, right):.9f}",
        "max_section_surface_move_m": f"{_max_section_surface_move(left, right):.9f}",
    }


def _airfoil_morph_step(left: Station, right: Station) -> float:
    return max(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(left.airfoil_xz, right.airfoil_xz)
    )


def _max_section_surface_move(left: Station, right: Station) -> float:
    return max(
        math.sqrt(
            ((b[0] * right.chord) - (a[0] * left.chord)) ** 2
            + (right.y - left.y) ** 2
            + ((right.z_le + b[1] * right.chord) - (left.z_le + a[1] * left.chord))
            ** 2
        )
        for a, b in zip(left.airfoil_xz, right.airfoil_xz)
    )


def _read_airfoil_dat(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            points.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if len(points) < 6:
        raise ValueError(f"too few airfoil DAT points: {path}")
    return points


def _resample_airfoil_open_te_cgrid(
    raw_points: Sequence[tuple[float, float]],
    *,
    points_per_side: int,
    airfoil_id: str,
    default_blunt_gap_over_chord: float = 5.0e-4,
    max_blunt_gap_over_chord: float = 1.0e-3,
    target_zero_te_gap_over_chord: float | None = None,
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    if target_zero_te_gap_over_chord is not None and target_zero_te_gap_over_chord < 0.0:
        raise ValueError("target zero-TE gap must be non-negative")
    if target_zero_te_gap_over_chord is not None and target_zero_te_gap_over_chord > max_blunt_gap_over_chord:
        raise ValueError("target zero-TE gap exceeds maximum")
    if default_blunt_gap_over_chord > max_blunt_gap_over_chord:
        raise ValueError("default TE blunt gap exceeds maximum")
    points = [(float(x), float(z)) for x, z in raw_points]
    leading_edge_index = min(range(len(points)), key=lambda idx: points[idx][0])
    if leading_edge_index == 0 or leading_edge_index == len(points) - 1:
        raise ValueError("Airfoil loop must run TE-upper -> LE -> TE-lower")

    upper = points[: leading_edge_index + 1]
    lower = points[leading_edge_index:]
    upper_x = _cosine_space_te_to_le(points_per_side)
    lower_x = list(reversed(upper_x))
    upper_loop = [(x, _interp_z(upper, x)) for x in upper_x]
    lower_loop = [(x, _interp_z(lower, x)) for x in lower_x[1:]]
    lower_loop = _repair_lower_branch_above_upper(upper_loop, lower_loop)

    raw_upper_te = points[0]
    raw_lower_te = points[-1]
    raw_te_gap = _distance_2d(raw_upper_te, raw_lower_te)
    te_perturbation: dict[str, Any]
    if raw_te_gap <= 1.0e-10:
        gap = default_blunt_gap_over_chord if target_zero_te_gap_over_chord is None else target_zero_te_gap_over_chord
        if gap > 0.0:
            te_center_x = 0.5 * (raw_upper_te[0] + raw_lower_te[0])
            te_center_z = 0.5 * (raw_upper_te[1] + raw_lower_te[1])
            upper_loop[0] = (te_center_x, te_center_z + 0.5 * gap)
            lower_loop[-1] = (te_center_x, te_center_z - 0.5 * gap)
            te_perturbation = {
                "introduced": True,
                "reason": "mathematically zero-thickness TE needs bounded C-grid collar gap",
                "gap_over_chord": gap,
                "max_allowed_gap_over_chord": max_blunt_gap_over_chord,
                "default_limit_over_chord": default_blunt_gap_over_chord,
            }
        else:
            upper_loop[0] = raw_upper_te
            lower_loop[-1] = raw_lower_te
            te_perturbation = {
                "introduced": False,
                "reason": "gap_0p00 baseline: mathematically sharp TE preserved without collar opening",
                "gap_over_chord": 0.0,
                "max_allowed_gap_over_chord": max_blunt_gap_over_chord,
                "default_limit_over_chord": default_blunt_gap_over_chord,
            }
    else:
        upper_loop[0] = raw_upper_te
        lower_loop[-1] = raw_lower_te
        te_perturbation = {
            "introduced": False,
            "reason": "finite source TE endpoints preserved",
            "gap_over_chord": raw_te_gap,
            "max_allowed_gap_over_chord": max_blunt_gap_over_chord,
            "default_limit_over_chord": default_blunt_gap_over_chord,
        }

    loop = upper_loop + lower_loop
    return (
        loop,
        _airfoil_geometry_report(
            raw_points,
            loop,
            airfoil_id=airfoil_id,
            airfoil_loop_mode="open_te_cgrid",
            te_perturbation=te_perturbation,
        ),
    )


def _airfoil_geometry_report(
    raw_points: Sequence[tuple[float, float]],
    resampled_loop: Sequence[tuple[float, float]],
    *,
    airfoil_id: str,
    airfoil_loop_mode: str,
    te_perturbation: dict[str, Any],
) -> dict[str, Any]:
    raw = [(float(x), float(z)) for x, z in raw_points]
    raw_chord = max(x for x, _z in raw) - min(x for x, _z in raw)
    new_chord = max(x for x, _z in resampled_loop) - min(x for x, _z in resampled_loop)
    raw_area = abs(_polygon_area(raw))
    new_area = abs(_polygon_area(resampled_loop))
    regularization_area_delta = 0.0
    max_regularization_displacement = 0.0
    if te_perturbation.get("introduced"):
        unregularized = list(resampled_loop)
        te_midpoint = (
            0.5 * (resampled_loop[0][0] + resampled_loop[-1][0]),
            0.5 * (resampled_loop[0][1] + resampled_loop[-1][1]),
        )
        unregularized[0] = te_midpoint
        unregularized[-1] = te_midpoint
        regularization_area_delta = new_area - abs(_polygon_area(unregularized))
        max_regularization_displacement = 0.5 * float(te_perturbation["gap_over_chord"])
    return {
        "airfoil_id": airfoil_id,
        "airfoil_loop_mode": airfoil_loop_mode,
        "raw_te_gap_over_chord": _distance_2d(raw[0], raw[-1]) / max(raw_chord, 1.0e-12),
        "resampled_te_gap_over_chord": _distance_2d(resampled_loop[0], resampled_loop[-1]) / max(new_chord, 1.0e-12),
        "raw_area_over_chord2": raw_area,
        "resampled_area_over_chord2": new_area,
        "area_delta_over_chord2": new_area - raw_area,
        "te_regularization_area_delta_over_chord2": regularization_area_delta,
        "max_te_regularization_displacement_over_chord": max_regularization_displacement,
        "raw_chord": raw_chord,
        "resampled_chord": new_chord,
        "chord_delta": new_chord - raw_chord,
        "te_perturbation_chord_delta": 0.0,
        "sref_planform_delta_over_chord2": 0.0,
        "sref_note": "TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged.",
        "te_perturbation": te_perturbation,
    }


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(points, [*points[1:], points[0]])
    )


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _required_float(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: float | None = None,
) -> float:
    raw = payload.get(key)
    if raw in (None, ""):
        if default is None:
            raise KeyError(key)
        return float(default)
    return float(raw)


def _require_close(name: str, observed: float, expected: float, tolerance: float) -> None:
    if abs(observed - expected) > tolerance:
        raise ValueError(f"{name}={observed} differs from expected {expected}")


def _lerp(left: float, right: float, eta: float) -> float:
    return float(left) + (float(right) - float(left)) * float(eta)
