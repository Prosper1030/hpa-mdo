from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEA_LEVEL_AIR_TABLE_PATH = (
    _REPO_ROOT / "data" / "atmosphere" / "sea_level_air_20_40c.yaml"
)
DRY_AIR_GAS_CONSTANT_J_PER_KG_K = 287.058
WATER_VAPOR_GAS_CONSTANT_J_PER_KG_K = 461.495
LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S = 1.8e-5


@dataclass(frozen=True)
class AirProperties:
    temperature_c: float
    pressure_pa: float
    relative_humidity_percent: float
    altitude_m: float
    density_kg_per_m3: float
    dynamic_viscosity_pa_s: float
    kinematic_viscosity_m2_per_s: float
    source: str
    table_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=4)
def _load_table(path: str) -> dict[str, Any]:
    table_path = Path(path)
    payload = yaml.safe_load(table_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Atmosphere table must contain a mapping: {table_path}")
    if payload.get("schema_version") != "sea_level_air_properties_v1":
        raise ValueError(
            "Atmosphere table schema_version must be sea_level_air_properties_v1."
        )
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Atmosphere table must contain non-empty rows.")
    temperatures = [float(row["temperature_c"]) for row in rows if isinstance(row, dict)]
    if temperatures != list(range(20, 41)):
        raise ValueError("Atmosphere table must contain integer Celsius rows 20..40.")
    return payload


def _lerp(left: float, right: float, fraction: float) -> float:
    return float(left) + (float(right) - float(left)) * float(fraction)


def _row_by_temperature(table: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["temperature_c"]): row for row in table["rows"]}


def interpolate_sea_level_air_properties(
    temperature_c: float,
    table_path: Path | str = DEFAULT_SEA_LEVEL_AIR_TABLE_PATH,
) -> AirProperties:
    """Return dry sea-level air properties from the 20-40 C table."""

    temp_c = float(temperature_c)
    table = _load_table(str(Path(table_path)))
    rows = _row_by_temperature(table)
    min_temp = min(rows)
    max_temp = max(rows)
    if temp_c < min_temp or temp_c > max_temp:
        raise ValueError(
            f"temperature_c must be within the sea-level air table range "
            f"{min_temp}..{max_temp} C."
        )

    lower = math.floor(temp_c)
    upper = math.ceil(temp_c)
    if lower == upper:
        row = rows[lower]
        density = float(row["density_kg_per_m3"])
        dynamic_viscosity = float(row["dynamic_viscosity_pa_s"])
    else:
        lower_row = rows[lower]
        upper_row = rows[upper]
        fraction = temp_c - lower
        density = _lerp(
            float(lower_row["density_kg_per_m3"]),
            float(upper_row["density_kg_per_m3"]),
            fraction,
        )
        dynamic_viscosity = _lerp(
            float(lower_row["dynamic_viscosity_pa_s"]),
            float(upper_row["dynamic_viscosity_pa_s"]),
            fraction,
        )

    return AirProperties(
        temperature_c=temp_c,
        pressure_pa=float(table["pressure_pa"]),
        relative_humidity_percent=0.0,
        altitude_m=0.0,
        density_kg_per_m3=density,
        dynamic_viscosity_pa_s=dynamic_viscosity,
        kinematic_viscosity_m2_per_s=dynamic_viscosity / density,
        source="sea_level_dry_air_table_linear_interpolation",
        table_path=str(Path(table_path)),
    )


def _saturation_vapor_pressure_pa(temperature_c: float) -> float:
    return 610.94 * math.exp((17.625 * float(temperature_c)) / (float(temperature_c) + 243.04))


def _tropospheric_pressure_pa(altitude_m: float) -> float:
    if altitude_m < -100.0 or altitude_m > 11000.0:
        raise ValueError(
            "environment.altitude_m must be within -100 m to 11000 m for the "
            "tropospheric density approximation."
        )
    return 101325.0 * (1.0 - 2.25577e-5 * float(altitude_m)) ** 5.25588


def air_properties_from_environment(
    *,
    temperature_c: float,
    relative_humidity_percent: float,
    altitude_m: float = 0.0,
    table_path: Path | str = DEFAULT_SEA_LEVEL_AIR_TABLE_PATH,
) -> AirProperties:
    """Resolve density and viscosity from the table plus humidity/altitude correction."""

    dry_table_props = interpolate_sea_level_air_properties(
        temperature_c=temperature_c,
        table_path=table_path,
    )
    temp_k = float(temperature_c) + 273.15
    altitude = float(altitude_m)
    relative_humidity = max(0.0, min(1.0, float(relative_humidity_percent) / 100.0))
    pressure_pa = (
        dry_table_props.pressure_pa
        if abs(altitude) <= 1.0e-12
        else _tropospheric_pressure_pa(altitude)
    )
    if abs(altitude) <= 1.0e-12 and relative_humidity == 0.0:
        density = dry_table_props.density_kg_per_m3
    else:
        saturation_vapor_pa = _saturation_vapor_pressure_pa(float(temperature_c))
        vapor_pa = relative_humidity * saturation_vapor_pa
        dry_pa = max(0.0, pressure_pa - vapor_pa)
        density = dry_pa / (DRY_AIR_GAS_CONSTANT_J_PER_KG_K * temp_k) + vapor_pa / (
            WATER_VAPOR_GAS_CONSTANT_J_PER_KG_K * temp_k
        )
    dynamic_viscosity = dry_table_props.dynamic_viscosity_pa_s
    source = (
        "sea_level_dry_air_table_linear_interpolation"
        if abs(altitude) <= 1.0e-12 and relative_humidity == 0.0
        else "sea_level_air_table_with_humidity_density_correction"
    )
    if abs(altitude) > 1.0e-12:
        source = "sea_level_air_table_with_humidity_altitude_density_correction"
    return AirProperties(
        temperature_c=float(temperature_c),
        pressure_pa=pressure_pa,
        relative_humidity_percent=float(relative_humidity_percent),
        altitude_m=altitude,
        density_kg_per_m3=density,
        dynamic_viscosity_pa_s=dynamic_viscosity,
        kinematic_viscosity_m2_per_s=dynamic_viscosity / density,
        source=source,
        table_path=str(Path(table_path)),
    )


__all__ = [
    "AirProperties",
    "DEFAULT_SEA_LEVEL_AIR_TABLE_PATH",
    "LEGACY_DEFAULT_DYNAMIC_VISCOSITY_PA_S",
    "air_properties_from_environment",
    "interpolate_sea_level_air_properties",
]
