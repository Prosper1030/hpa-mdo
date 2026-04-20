from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hpa_mdo.aero.vsp_introspect import summarize_vsp_surfaces
from hpa_mdo.core.config import load_config


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

    surfaces = {
        key: value
        for key, value in (
            ("main_wing", summary.get("main_wing")),
            ("horizontal_tail", summary.get("horizontal_tail")),
            ("vertical_fin", summary.get("vertical_fin")),
        )
        if value is not None
    }
    tail_geometry_confirmed = "horizontal_tail" in surfaces and "vertical_fin" in surfaces
    control_surface_contract_confirmed = tail_geometry_confirmed and all(
        len(surface.get("controls") or []) > 0
        for name, surface in surfaces.items()
        if name in {"horizontal_tail", "vertical_fin"}
    )
    return {
        "origin_vsp_path": str(origin_vsp),
        "tail_geometry_confirmed": tail_geometry_confirmed,
        "control_surface_contract_confirmed": control_surface_contract_confirmed,
        "surfaces": surfaces,
    }


def write_origin_geometry_contract(output_dir: str | Path, contract: dict[str, Any]) -> str:
    path = Path(output_dir).expanduser().resolve() / "origin_geometry_contract.json"
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return str(path)
