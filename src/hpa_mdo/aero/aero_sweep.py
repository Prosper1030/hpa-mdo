"""Shared aerodynamic sweep helpers for VSPAero and SU2."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from hpa_mdo.aero.vsp_aero import VSPAeroParser


@dataclass(frozen=True)
class AeroSweepPoint:
    solver: str
    alpha_deg: float
    cl: float | None
    cd: float | None
    cm: float | None
    lift_n: float | None
    drag_n: float | None
    source_path: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_key(key: Any) -> str:
    normalized = str(key).strip().strip('"').strip("'").strip()
    normalized = normalized.replace("-", "_").replace(" ", "")
    return normalized.upper()


def _lookup_metric(row: dict[str, Any], *keys: str) -> float | None:
    normalized = {_normalize_key(key): value for key, value in row.items()}
    for key in keys:
        parsed = _parse_float(normalized.get(_normalize_key(key)))
        if parsed is not None:
            return parsed
    return None


def _force_from_coefficient(
    coefficient: float | None,
    density_kgpm3: float | None,
    velocity_mps: float | None,
    reference_area_m2: float | None,
) -> float | None:
    if (
        coefficient is None
        or density_kgpm3 is None
        or velocity_mps is None
        or reference_area_m2 is None
    ):
        return None
    dynamic_pressure = 0.5 * density_kgpm3 * velocity_mps**2
    return float(coefficient * dynamic_pressure * reference_area_m2)


def _read_vspaero_reference_values(lod_path: Path) -> dict[str, float]:
    text = Path(lod_path).read_text(encoding="utf-8", errors="replace")
    return VSPAeroParser._parse_header(text)


def build_vspaero_sweep_points(
    *,
    lod_path: str | Path,
    polar_path: str | Path,
) -> list[AeroSweepPoint]:
    lod = Path(lod_path)
    polar = Path(polar_path)
    ref = _read_vspaero_reference_values(lod)
    parser = VSPAeroParser(lod, polar_path=polar)
    polar_df = parser.get_polar_df()
    if polar_df is None or polar_df.empty:
        raise ValueError(f"VSPAero polar file has no data: {polar}")

    density = _parse_float(ref.get("rho"))
    velocity = _parse_float(ref.get("vinf"))
    sref = _parse_float(ref.get("sref"))
    points: list[AeroSweepPoint] = []

    for _, row in polar_df.iterrows():
        row_dict = row.to_dict()
        alpha = _lookup_metric(row_dict, "AOA", "ALPHA")
        if alpha is None:
            raise ValueError(f"VSPAero polar row missing AoA: {row_dict}")
        cl = _lookup_metric(row_dict, "CLTOT", "CL")
        cd = _lookup_metric(row_dict, "CDTOT", "CD", "DRAG")
        cm = _lookup_metric(row_dict, "CMOY", "CM", "CMYTOT", "MOMENT_Y")
        points.append(
            AeroSweepPoint(
                solver="vspaero",
                alpha_deg=float(alpha),
                cl=cl,
                cd=cd,
                cm=cm,
                lift_n=_force_from_coefficient(cl, density, velocity, sref),
                drag_n=_force_from_coefficient(cd, density, velocity, sref),
                source_path=str(polar.resolve()),
                notes="reference_from_lod",
            )
        )

    return sorted(points, key=lambda point: point.alpha_deg)


def _read_history_csv(history_path: Path) -> list[dict[str, Any]]:
    with history_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _read_history_dat(history_path: Path) -> list[dict[str, Any]]:
    lines = history_path.read_text(encoding="utf-8", errors="replace").splitlines()
    data_lines = [line.strip() for line in lines if line.strip()]
    if len(data_lines) < 2:
        raise ValueError(f"history file has insufficient data: {history_path}")

    header = [column.strip().strip('"') for column in data_lines[0].split(",")]
    if len(header) == 1:
        header = data_lines[0].replace("\t", " ").split()

    rows: list[dict[str, Any]] = []
    for line in data_lines[1:]:
        values = [column.strip().strip('"') for column in line.split(",")]
        if len(values) == 1:
            values = line.replace("\t", " ").split()
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values)))
    return rows


def _load_history_rows(history_path: Path) -> list[dict[str, Any]]:
    if history_path.suffix.lower() == ".csv":
        return _read_history_csv(history_path)
    return _read_history_dat(history_path)


def _find_history_file(case_dir: Path) -> Path | None:
    for candidate in (
        case_dir / "history.csv",
        case_dir / "history.dat",
        case_dir / "conv_history.csv",
        case_dir / "conv_history.dat",
    ):
        if candidate.exists():
            return candidate
    return None


def _parse_su2_cfg(cfg_path: Path) -> dict[str, str]:
    if not cfg_path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in cfg_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%") or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[_normalize_key(key)] = value.strip()
    return parsed


_FLOAT_TOKEN_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _parse_velocity_from_cfg(cfg_values: dict[str, str]) -> float | None:
    vector_text = cfg_values.get("INC_VELOCITY_INIT")
    if vector_text:
        components = [float(token) for token in _FLOAT_TOKEN_RE.findall(vector_text)]
        if components:
            return float(math.sqrt(sum(component**2 for component in components)))

    for key in ("FREESTREAM_VELOCITY", "REF_VELOCITY"):
        value = _parse_float(cfg_values.get(key))
        if value is not None:
            return value
    return None


def _alpha_from_metadata(case_dir: Path) -> tuple[float | None, str | None]:
    for candidate in (
        case_dir / "case_metadata.json",
        case_dir / "metadata.json",
        case_dir / "case.json",
    ):
        payload = _load_json_dict(candidate)
        if not payload:
            continue
        for key in ("alpha_deg", "aoa_deg", "aoa", "alpha"):
            value = _parse_float(payload.get(key))
            if value is not None:
                return value, f"metadata:{candidate.name}"
    return None, None


def _decode_alpha_token(token: str) -> float | None:
    stripped = token.strip().lower()
    if not stripped:
        return None
    direct = _parse_float(stripped)
    if direct is not None:
        return direct

    # Accept names like `m2p0` -> -2.0
    sign = -1.0 if stripped.startswith("m") else 1.0
    if stripped[:1] in {"m", "p"}:
        stripped = stripped[1:]
    stripped = stripped.replace("p", ".")
    value = _parse_float(stripped)
    if value is None:
        return None
    return sign * value


_ALPHA_NAME_RE = re.compile(r"(?:^|[_-])(?:alpha|aoa)[_-]?([A-Za-z0-9.+-]+)(?:$|[_-])", re.IGNORECASE)


def _alpha_from_case_name(case_dir: Path) -> tuple[float | None, str | None]:
    match = _ALPHA_NAME_RE.search(case_dir.name)
    if match is None:
        return None, None
    value = _decode_alpha_token(match.group(1))
    if value is None:
        return None, None
    return value, "case_name"


def _alpha_from_cfg(cfg_values: dict[str, str]) -> tuple[float | None, str | None]:
    value = _parse_float(cfg_values.get("AOA"))
    if value is not None:
        return value, "cfg"
    return None, None


def _resolve_case_alpha(case_dir: Path, cfg_values: dict[str, str]) -> tuple[float, str]:
    for resolver in (_alpha_from_metadata, _alpha_from_case_name):
        value, source = resolver(case_dir)
        if value is not None and source is not None:
            return float(value), source
    value, source = _alpha_from_cfg(cfg_values)
    if value is not None and source is not None:
        return float(value), source
    raise ValueError(f"could not determine alpha for SU2 case: {case_dir}")


def _resolve_case_paths(sweep_dir: Path) -> list[Path]:
    root_history = _find_history_file(sweep_dir)
    if root_history is not None:
        return [sweep_dir]
    case_dirs = sorted(
        child for child in sweep_dir.iterdir()
        if child.is_dir() and _find_history_file(child) is not None
    )
    if not case_dirs:
        raise ValueError(f"no SU2 history cases found under: {sweep_dir}")
    return case_dirs


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _load_case_metadata(case_dir: Path) -> dict[str, Any]:
    for candidate in (
        case_dir / "case_metadata.json",
        case_dir / "metadata.json",
        case_dir / "case.json",
    ):
        payload = _load_json_dict(candidate)
        if payload:
            return payload
    return {}


def _load_run_summary_cases(sweep_dir: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json_dict(sweep_dir / "su2_run_summary.json")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        return {}

    cases_by_name: dict[str, dict[str, Any]] = {}
    for case in raw_cases:
        if not isinstance(case, dict):
            continue
        case_name = case.get("case_name")
        if case_name:
            cases_by_name[str(case_name)] = case
    return cases_by_name


def _resolve_run_summary_case(
    *,
    sweep_dir: Path,
    case_dir: Path,
    run_summary_cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    direct_match = run_summary_cases.get(case_dir.name)
    if direct_match is not None:
        return direct_match

    if case_dir == sweep_dir and len(run_summary_cases) == 1:
        return next(iter(run_summary_cases.values()))

    return {}


def _build_su2_case_notes(
    *,
    alpha_source: str,
    case_metadata: dict[str, Any],
    run_summary_case: dict[str, Any],
) -> str:
    note_parts = [f"alpha_source={alpha_source}"]

    case_status = run_summary_case.get("status") or case_metadata.get("run_status")
    if case_status:
        note_parts.append(f"run_status={case_status}")

    mesh_preset = case_metadata.get("mesh_preset") or run_summary_case.get("mesh_preset")
    if mesh_preset:
        note_parts.append(f"mesh_preset={mesh_preset}")

    return "; ".join(note_parts)


def load_su2_alpha_sweep(sweep_dir: str | Path) -> list[AeroSweepPoint]:
    root = Path(sweep_dir)
    case_dirs = _resolve_case_paths(root)
    run_summary_cases = _load_run_summary_cases(root)
    points: list[AeroSweepPoint] = []

    for case_dir in case_dirs:
        history_path = _find_history_file(case_dir)
        if history_path is None:
            continue
        rows = _load_history_rows(history_path)
        if not rows:
            raise ValueError(f"history file has no rows: {history_path}")
        last_row = rows[-1]
        cfg_values = _parse_su2_cfg(case_dir / "su2_runtime.cfg")
        alpha_deg, alpha_source = _resolve_case_alpha(case_dir, cfg_values)
        case_metadata = _load_case_metadata(case_dir)
        run_summary_case = _resolve_run_summary_case(
            sweep_dir=root,
            case_dir=case_dir,
            run_summary_cases=run_summary_cases,
        )
        density = _parse_float(cfg_values.get("INC_DENSITY_INIT")) or _parse_float(
            cfg_values.get("FREESTREAM_DENSITY")
        )
        velocity = _parse_velocity_from_cfg(cfg_values)
        ref_area = _parse_float(cfg_values.get("REF_AREA"))
        cl = _lookup_metric(last_row, "LIFT", "CL", "CFZ")
        cd = _lookup_metric(last_row, "DRAG", "CD", "CFX")
        cm = _lookup_metric(last_row, "MOMENT_Y", "CMY", "CM", "CMYTOT")
        points.append(
            AeroSweepPoint(
                solver="su2",
                alpha_deg=alpha_deg,
                cl=cl,
                cd=cd,
                cm=cm,
                lift_n=_force_from_coefficient(cl, density, velocity, ref_area),
                drag_n=_force_from_coefficient(cd, density, velocity, ref_area),
                source_path=str(history_path.resolve()),
                notes=_build_su2_case_notes(
                    alpha_source=alpha_source,
                    case_metadata=case_metadata,
                    run_summary_case=run_summary_case,
                ),
            )
        )

    return sorted(points, key=lambda point: point.alpha_deg)


def sweep_points_to_dataframe(points: Iterable[AeroSweepPoint]) -> pd.DataFrame:
    columns = [
        "solver",
        "alpha_deg",
        "cl",
        "cd",
        "cm",
        "lift_n",
        "drag_n",
        "source_path",
        "notes",
    ]
    rows = [point.to_dict() for point in points]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows)
    return df[columns].sort_values(["solver", "alpha_deg"]).reset_index(drop=True)
