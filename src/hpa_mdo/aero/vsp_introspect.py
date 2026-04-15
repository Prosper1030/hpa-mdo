"""Auto-extract aircraft geometry from a reference .vsp3 file.

Goal: make the MDO pipeline accept **any .vsp3 that follows the standard
HPA convention** (one symmetric main wing + one symmetric h-tail + one
vertical fin), without the user having to hand-edit YAML geometry for
every new design.

Convention
----------
*   The **main wing** is the largest symmetric (`Sym_Planar_Flag = XZ`)
    WING geom whose span exceeds the h-tail span.
*   The **horizontal tail** is the second-largest symmetric WING geom,
    located downstream (larger Xrel than the main wing).
*   The **vertical fin** is the largest non-symmetric WING geom with
    either a non-zero z-rotation (~90°) or its root-to-tip axis
    pointing vertically.

When the heuristic is ambiguous we fall back to name matching (case
insensitive, stripping non-alphanumerics): {"mainwing","main"} →
main wing; {"elevator","htail","horizontaltail","hstab"} → h-tail;
{"fin","vtail","verticaltail","vstab","rudder"} → v-fin.

The output is a plain dict (JSON-serialisable), so callers can either
feed it to HPAConfig by merging, or dump it for debugging.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MAIN_ALIASES = {"mainwing", "main", "wing"}
_HTAIL_ALIASES = {"elevator", "htail", "horizontaltail", "hstab", "tailplane"}
_VFIN_ALIASES = {"fin", "vtail", "verticaltail", "vstab", "rudder", "verticalfin"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _safe_get(vsp: Any, geom_id: str, name: str, alt: str = "") -> float:
    """Best-effort `GetParmVal` for a geom parm, returning 0.0 on failure."""
    for parm_name in (name, alt):
        if not parm_name:
            continue
        try:
            parm_id = vsp.FindParm(geom_id, parm_name, "XForm")
            if parm_id:
                return float(vsp.GetParmVal(parm_id))
        except Exception:
            continue
    return 0.0


def _sym_xz(vsp: Any, geom_id: str) -> bool:
    try:
        pid = vsp.FindParm(geom_id, "Sym_Planar_Flag", "Sym")
        if pid:
            return bool(int(vsp.GetParmVal(pid)) & getattr(vsp, "SYM_XZ", 2))
    except Exception:
        pass
    return False


def _extract_wing_schedule(vsp: Any, wing_id: str) -> List[Dict[str, float]]:
    """Return [{y, chord, dihedral_deg}, ...] from a WING geom's XSecs."""
    try:
        surf = vsp.GetXSecSurf(wing_id, 0)
        n = int(vsp.GetNumXSec(surf))
    except Exception:
        return []
    schedule: List[Dict[str, float]] = []
    y_accum = 0.0
    for i in range(1, n):
        try:
            xs = vsp.GetXSec(surf, i)
            root_c = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Root_Chord")))
            tip_c = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Tip_Chord")))
            span = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Span")))
            dih = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Dihedral")))
        except Exception:
            continue
        if span <= 1e-9:
            continue
        if not schedule:
            schedule.append({"y": 0.0, "chord": root_c, "dihedral_deg": dih})
        y_accum += span
        schedule.append({"y": y_accum, "chord": tip_c, "dihedral_deg": dih})
    return schedule


def _wing_extent(schedule: List[Dict[str, float]]) -> Dict[str, float]:
    """Compute span / root / tip from a schedule."""
    if not schedule:
        return {"half_span": 0.0, "root_chord": 0.0, "tip_chord": 0.0}
    half = float(schedule[-1]["y"])
    return {
        "half_span": half,
        "root_chord": float(schedule[0]["chord"]),
        "tip_chord": float(schedule[-1]["chord"]),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize_vsp_surfaces(vsp_path: str | Path) -> Dict[str, Any]:
    """Read a .vsp3 and return a dict describing its main wing + empennage.

    Returns
    -------
    dict with keys ``main_wing``, ``horizontal_tail``, ``vertical_fin``,
    each either a sub-dict with extracted parms or ``None`` when the
    surface is absent.  Always includes ``source_path`` for provenance.
    """
    path = Path(vsp_path)
    if not path.is_file():
        raise FileNotFoundError(f"VSP file not found: {path}")

    try:
        import openvsp as vsp  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "openvsp python bindings required to introspect a .vsp3 file."
        ) from exc

    vsp.ClearVSPModel()
    vsp.ReadVSPFile(str(path))
    vsp.Update()

    geoms: List[Dict[str, Any]] = []
    for gid in vsp.FindGeoms():
        try:
            type_name = vsp.GetGeomTypeName(gid) if hasattr(vsp, "GetGeomTypeName") else ""
        except Exception:
            type_name = ""
        if type_name and type_name.upper() != "WING":
            continue
        name = vsp.GetGeomName(gid)
        sched = _extract_wing_schedule(vsp, gid)
        extent = _wing_extent(sched)
        geoms.append({
            "id": gid,
            "name": name,
            "name_norm": _norm(name),
            "schedule": sched,
            "half_span": extent["half_span"],
            "root_chord": extent["root_chord"],
            "tip_chord": extent["tip_chord"],
            "sym_xz": _sym_xz(vsp, gid),
            "x_location": _safe_get(vsp, gid, "X_Rel_Location", "X_Location"),
            "y_location": _safe_get(vsp, gid, "Y_Rel_Location", "Y_Location"),
            "z_location": _safe_get(vsp, gid, "Z_Rel_Location", "Z_Location"),
            "x_rotation_deg": _safe_get(vsp, gid, "X_Rel_Rotation", "X_Rotation"),
            "y_rotation_deg": _safe_get(vsp, gid, "Y_Rel_Rotation", "Y_Rotation"),
            "z_rotation_deg": _safe_get(vsp, gid, "Z_Rel_Rotation", "Z_Rotation"),
        })

    # Clear so we don't leak state.
    try:
        vsp.ClearVSPModel()
    except Exception:
        pass

    main_w = _pick_main_wing(geoms)
    h_tail = _pick_h_tail(geoms, exclude_id=main_w["id"] if main_w else None)
    v_fin = _pick_v_fin(geoms)

    result: Dict[str, Any] = {
        "source_path": str(path),
        "main_wing": _pack_surface(main_w, "main_wing"),
        "horizontal_tail": _pack_surface(h_tail, "horizontal_tail"),
        "vertical_fin": _pack_surface(v_fin, "vertical_fin"),
    }
    _log_summary(result)
    return result


def _pick_main_wing(geoms: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # Alias match first.
    for g in geoms:
        if g["name_norm"] in _MAIN_ALIASES and g["sym_xz"]:
            return g
    # Fallback: largest symmetric wing by full span (2×half_span).
    syms = [g for g in geoms if g["sym_xz"]]
    syms.sort(key=lambda g: g["half_span"], reverse=True)
    return syms[0] if syms else None


def _pick_h_tail(
    geoms: List[Dict[str, Any]],
    exclude_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    for g in geoms:
        if g["id"] == exclude_id:
            continue
        if g["name_norm"] in _HTAIL_ALIASES and g["sym_xz"]:
            return g
    # Fallback: second-largest symmetric wing.
    syms = [g for g in geoms if g["sym_xz"] and g["id"] != exclude_id]
    syms.sort(key=lambda g: g["half_span"], reverse=True)
    return syms[0] if syms else None


def _pick_v_fin(geoms: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for g in geoms:
        if g["name_norm"] in _VFIN_ALIASES and not g["sym_xz"]:
            return g
    # Fallback: any non-symmetric wing with x_rotation near 90° (rolled up).
    for g in geoms:
        if not g["sym_xz"] and abs(abs(g["x_rotation_deg"]) - 90.0) < 15.0:
            return g
    # Last resort: any non-symmetric wing.
    for g in geoms:
        if not g["sym_xz"]:
            return g
    return None


def _pack_surface(g: Optional[Dict[str, Any]], kind: str) -> Optional[Dict[str, Any]]:
    if g is None:
        return None
    full_span = 2.0 * g["half_span"] if g["sym_xz"] else g["half_span"]
    if kind == "vertical_fin" and not g["sym_xz"]:
        # Vertical fin: schedule's y axis IS the z extent when x-rotated 90°.
        full_span = g["half_span"]
    return {
        "name": g["name"],
        "span_m": full_span,
        "half_span_m": g["half_span"],
        "root_chord_m": g["root_chord"],
        "tip_chord_m": g["tip_chord"],
        "x_location": g["x_location"],
        "y_location": g["y_location"],
        "z_location": g["z_location"],
        "x_rotation_deg": g["x_rotation_deg"],
        "y_rotation_deg": g["y_rotation_deg"],
        "z_rotation_deg": g["z_rotation_deg"],
        "sym_xz": g["sym_xz"],
        "n_schedule_stations": len(g["schedule"]),
    }


def _log_summary(result: Dict[str, Any]) -> None:
    for kind in ("main_wing", "horizontal_tail", "vertical_fin"):
        entry = result[kind]
        if entry is None:
            logger.info("VSP introspect: %s not detected", kind)
            continue
        logger.info(
            "VSP introspect: %s = %s  span=%.3f m  root=%.4f m  tip=%.4f m",
            kind,
            entry["name"],
            entry["span_m"],
            entry["root_chord_m"],
            entry["tip_chord_m"],
        )


def merge_into_config_dict(
    base_cfg_dict: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Non-destructively override wing / empennage geometry from VSP summary.

    Only geometry fields are touched; engineering fields (materials,
    safety factors, solver, spar segments) are left exactly as in the
    base config.  Returns a new dict (input is not mutated).
    """
    out = {k: (dict(v) if isinstance(v, dict) else v)
           for k, v in base_cfg_dict.items()}

    mw = summary.get("main_wing")
    if mw is not None:
        out.setdefault("wing", {})
        out["wing"]["span"] = float(mw["span_m"])
        out["wing"]["root_chord"] = float(mw["root_chord_m"])
        out["wing"]["tip_chord"] = float(mw["tip_chord_m"])

    ht = summary.get("horizontal_tail")
    if ht is not None:
        out.setdefault("horizontal_tail", {})
        out["horizontal_tail"]["enabled"] = True
        out["horizontal_tail"]["name"] = ht["name"]
        out["horizontal_tail"]["span"] = float(ht["span_m"])
        out["horizontal_tail"]["root_chord"] = float(ht["root_chord_m"])
        out["horizontal_tail"]["tip_chord"] = float(ht["tip_chord_m"])
        out["horizontal_tail"]["x_location"] = float(ht["x_location"])
        out["horizontal_tail"]["y_location"] = float(ht["y_location"])
        out["horizontal_tail"]["z_location"] = float(ht["z_location"])

    vf = summary.get("vertical_fin")
    if vf is not None:
        out.setdefault("vertical_fin", {})
        out["vertical_fin"]["enabled"] = True
        out["vertical_fin"]["name"] = vf["name"]
        out["vertical_fin"]["span"] = float(vf["span_m"])
        out["vertical_fin"]["root_chord"] = float(vf["root_chord_m"])
        out["vertical_fin"]["tip_chord"] = float(vf["tip_chord_m"])
        out["vertical_fin"]["x_location"] = float(vf["x_location"])
        out["vertical_fin"]["y_location"] = float(vf["y_location"])
        out["vertical_fin"]["z_location"] = float(vf["z_location"])
        out["vertical_fin"]["x_rotation_deg"] = float(vf["x_rotation_deg"])

    # Absolute vsp_model path goes into io.
    out.setdefault("io", {})
    out["io"]["vsp_model"] = str(summary["source_path"])

    return out


__all__ = ["summarize_vsp_surfaces", "merge_into_config_dict"]
