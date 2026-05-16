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

from hpa_meshing.mesh_native.blackcat import _resample_airfoil_loop  # noqa: E402
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


def load_baseline_authority(
    *,
    n_perim: int,
    geometry_dir: Path | str = DEFAULT_GEOMETRY_DIR,
) -> BaselineAuthority:
    if n_perim < 16 or n_perim % 2:
        raise ValueError("n_perim must be an even integer >= 16")

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
    stations: list[Station] = []
    for row in rows:
        dat_path = Path(row["airfoil_dat_path"])
        key = str(dat_path)
        loop = airfoil_cache.get(key)
        if loop is None:
            loop = _resample_airfoil_loop(
                _read_airfoil_dat(dat_path),
                points_per_side=points_per_side,
            )
            if len(loop) != n_perim:
                raise ValueError(f"airfoil resampling count mismatch for {dat_path}")
            airfoil_cache[key] = loop
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
