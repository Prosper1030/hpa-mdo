from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hpa_mdo.aero.vsp_introspect import summarize_vsp_surfaces
from hpa_mdo.core.config import load_config


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _surface_contract(kind: str, surface: dict[str, Any]) -> dict[str, Any]:
    controls = list(surface.get("controls") or [])
    control_names = [
        str(control.get("name"))
        for control in controls
        if isinstance(control, dict) and control.get("name") is not None
    ]
    return {
        "kind": kind,
        "name": surface.get("name"),
        "detected": True,
        "span_m": _coerce_float(surface.get("span_m") or surface.get("span")),
        "root_chord_m": _coerce_float(surface.get("root_chord_m") or surface.get("root_chord")),
        "tip_chord_m": _coerce_float(surface.get("tip_chord_m") or surface.get("tip_chord")),
        "location": {
            "x": _coerce_float(surface.get("x_location")),
            "y": _coerce_float(surface.get("y_location")),
            "z": _coerce_float(surface.get("z_location")),
        },
        "rotation_deg": {
            "x": _coerce_float(surface.get("x_rotation_deg")),
            "y": _coerce_float(surface.get("y_rotation_deg")),
            "z": _coerce_float(surface.get("z_rotation_deg")),
        },
        "symmetry_xz": bool(surface.get("sym_xz")),
        "station_count": int(surface.get("n_schedule_stations") or len(surface.get("schedule") or [])),
        "control_count": len(controls),
        "control_names": control_names,
    }


def build_origin_geometry_contract(
    *,
    config_path: str | Path,
    cfg: Any | None = None,
) -> dict[str, Any]:
    if cfg is None:
        cfg = load_config(config_path)
    origin_vsp = Path(cfg.io.vsp_model).expanduser().resolve()
    airfoil_dir = getattr(getattr(cfg, "io", None), "airfoil_dir", None)
    summary = summarize_vsp_surfaces(origin_vsp, airfoil_dir=airfoil_dir)

    surfaces: dict[str, Any] = {}
    for key in ("main_wing", "horizontal_tail", "vertical_fin"):
        surface = summary.get(key)
        if surface is not None:
            surfaces[key] = _surface_contract(key, surface)

    tail_geometry_confirmed = "horizontal_tail" in surfaces and "vertical_fin" in surfaces
    control_surface_contract_confirmed = tail_geometry_confirmed and all(
        surfaces[name]["control_count"] > 0
        for name in ("horizontal_tail", "vertical_fin")
        if name in surfaces
    )
    return {
        "contract_version": 1,
        "origin_vsp_path": str(origin_vsp),
        "tail_geometry_confirmed": tail_geometry_confirmed,
        "control_surface_contract_confirmed": control_surface_contract_confirmed,
        "surfaces": surfaces,
    }


def write_origin_geometry_contract(output_dir: str | Path, contract: dict[str, Any]) -> str:
    path = Path(output_dir).expanduser().resolve() / "origin_geometry_contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return str(path)
