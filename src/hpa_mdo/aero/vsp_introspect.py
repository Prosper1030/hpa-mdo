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

Phase 2 additions (M-VSP2)
--------------------------
*   Per-station airfoil extraction (FILE_AIRFOIL / NACA four-series /
    CST / ...).  Pure-dict output — optional ``airfoil_dir`` matches
    FILE_AIRFOIL thickness against on-disk ``.dat`` files.
*   SubSurface control-surface detection (eta_start / eta_end /
    chord-fraction).  Written to a sidecar ``controls.json`` by
    callers because ``HPAConfig`` does not yet have a control schema.
*   Segment auto-scaling in ``merge_into_config_dict`` so that a
    template tuned for ``blackcat_004`` (half-span 16.5 m) also works
    with different-span aircraft.
*   Continuous dihedral schedule ``[[y, z], ...]`` accumulated from
    per-segment ``Span × sin(Dihedral)``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_MAIN_ALIASES = {"mainwing", "main", "wing"}
_HTAIL_ALIASES = {"elevator", "htail", "horizontaltail", "hstab", "tailplane"}
_VFIN_ALIASES = {"fin", "vtail", "verticaltail", "vstab", "rudder", "verticalfin"}

# Conservative clamp on SubSurface Eta parms to avoid VSP parametric
# singularities at 0.0 and 1.0.
_ETA_CLAMP_LO = 0.001
_ETA_CLAMP_HI = 0.999


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


def _get_xsec_parm(vsp: Any, xs: Any, name: str) -> Optional[float]:
    """Best-effort GetParmVal on an XSec parm; return None on failure."""
    try:
        pid = vsp.GetXSecParm(xs, name)
        if pid:
            return float(vsp.GetParmVal(pid))
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Airfoil extraction (Phase 2)
# ---------------------------------------------------------------------------


def _naca_four_series_name(camber_frac: float, camber_loc: float, tc: float) -> str:
    """Construct a NACA four-series name string from VSP parms.

    VSP stores:
      * Camber        — maximum camber as chord fraction (e.g. 0.02 → NACA2xxx)
      * CamberLoc     — chordwise location of max camber as fraction (0.4 → NACA_4_)
      * ThickChord    — maximum thickness as chord fraction (0.12 → NACAxx12)
    """
    d1 = int(round(camber_frac * 100))
    d2 = int(round(camber_loc * 10))
    d34 = int(round(tc * 100))
    # Clamp to valid ranges; malformed digits just result in a best-effort name.
    d1 = max(0, min(9, d1))
    d2 = max(0, min(9, d2))
    d34 = max(0, min(99, d34))
    return f"NACA {d1}{d2}{d34:02d}"


def _match_afile_by_tc(
    tc: float,
    airfoil_dir: Path,
    tolerance_tc: float = 0.005,
) -> Optional[str]:
    """Scan ``airfoil_dir`` for ``.dat`` files whose thickness matches ``tc``.

    Returns the closest match's stem (without ``.dat``) if it's within
    ``tolerance_tc``; otherwise ``None``.  Thickness is estimated by
    reading XY points and computing ``max(z) - min(z)`` at matched x
    (Selig format ≈ 50–200 rows).
    """
    if not airfoil_dir.is_dir():
        return None
    best: Optional[Tuple[float, str]] = None
    for dat in sorted(airfoil_dir.glob("*.dat")):
        try:
            pts = _read_selig_dat(dat)
        except Exception:
            continue
        file_tc = _estimate_max_tc(pts)
        if file_tc is None:
            continue
        err = abs(file_tc - tc)
        if best is None or err < best[0]:
            best = (err, dat.stem)
    if best is None or best[0] > tolerance_tc:
        return None
    return best[1]


def _read_selig_dat(path: Path) -> List[Tuple[float, float]]:
    """Parse a Selig ``.dat`` airfoil file; skip a 1-line header if present."""
    pts: List[Tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        bits = line.split()
        if len(bits) < 2:
            continue
        try:
            x = float(bits[0]); z = float(bits[1])
        except ValueError:
            continue  # header row
        # Selig-normalised coords: 0 ≤ x ≤ 1 (tolerate slight over-shoot)
        if -0.01 <= x <= 1.01:
            pts.append((x, z))
    return pts


def _estimate_max_tc(pts: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Estimate max t/c by pairing upper/lower surface points at matched x."""
    if len(pts) < 6:
        return None
    # Simple approach: group into x-bins of 0.02 width, take max(z)-min(z).
    bins: Dict[int, List[float]] = {}
    for x, z in pts:
        key = int(round(x * 50))  # 0.02 bin
        bins.setdefault(key, []).append(z)
    best_tc = 0.0
    for zs in bins.values():
        if len(zs) >= 2:
            best_tc = max(best_tc, max(zs) - min(zs))
    return best_tc if best_tc > 0 else None


def _extract_airfoil_refs(
    vsp: Any,
    wing_id: str,
    schedule: Sequence[Dict[str, float]],
    airfoil_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return per-station airfoil metadata for a wing.

    Parameters
    ----------
    vsp
        The ``openvsp`` module.
    wing_id
        WING geom id.
    schedule
        Output of ``_extract_wing_schedule`` — used to align station y
        values with the XSec index.
    airfoil_dir
        Optional directory of Selig ``.dat`` files.  If provided we try
        to match FILE_AIRFOIL XSecs by max t/c.

    Returns
    -------
    list of dicts with ``{station_y, source, name, thickness_tc}``
    """
    try:
        surf = vsp.GetXSecSurf(wing_id, 0)
        n = int(vsp.GetNumXSec(surf))
    except Exception:
        return []

    refs: List[Dict[str, Any]] = []
    for i in range(n):
        try:
            xs = vsp.GetXSec(surf, i)
            shape = int(vsp.GetXSecShape(xs))
        except Exception:
            continue

        station_y = float(schedule[i]["y"]) if i < len(schedule) else float("nan")

        if shape == getattr(vsp, "XS_FILE_AIRFOIL", -1):
            tc = _get_xsec_parm(vsp, xs, "ThickChord") or 0.0
            name = None
            if airfoil_dir is not None:
                name = _match_afile_by_tc(tc, Path(airfoil_dir))
            refs.append({
                "station_y": station_y,
                "source": "afile",
                "name": name,
                "thickness_tc": tc,
            })
            continue

        if shape == getattr(vsp, "XS_FOUR_SERIES", -1):
            camber = _get_xsec_parm(vsp, xs, "Camber") or 0.0
            camber_loc = _get_xsec_parm(vsp, xs, "CamberLoc") or 0.0
            tc = _get_xsec_parm(vsp, xs, "ThickChord") or 0.0
            refs.append({
                "station_y": station_y,
                "source": "naca",
                "name": _naca_four_series_name(camber, camber_loc, tc),
                "thickness_tc": tc,
            })
            continue

        # Fallback: return the VSP shape constant as an opaque tag.
        tc = _get_xsec_parm(vsp, xs, "ThickChord")
        refs.append({
            "station_y": station_y,
            "source": f"vsp_shape_{shape}",
            "name": None,
            "thickness_tc": tc if tc is not None else 0.0,
        })

    return refs


# ---------------------------------------------------------------------------
# Control surface extraction (Phase 2)
# ---------------------------------------------------------------------------


def _classify_control_name(name: str) -> str:
    """Map a SubSurface name to a coarse control-type label."""
    n = _norm(name)
    if "aileron" in n:
        return "aileron"
    if "flap" in n and "flap" != n:  # "flap" alone is too generic, keep "flap"
        return "flap"
    if n == "flap":
        return "flap"
    if "elev" in n or "htail" in n or "stab" in n:
        return "elevator"
    if "rudd" in n or "fin" in n or "vtail" in n:
        return "rudder"
    if "spoil" in n:
        return "spoiler"
    return "unknown"


def _extract_controls(vsp: Any, wing_id: str) -> List[Dict[str, Any]]:
    """Return one dict per SubSurface of type SS_CONTROL on ``wing_id``."""
    try:
        n_ss = int(vsp.GetNumSubSurf(wing_id))
    except Exception:
        return []
    if n_ss <= 0:
        return []

    ss_control_const = getattr(vsp, "SS_CONTROL", 3)
    out: List[Dict[str, Any]] = []
    for i in range(n_ss):
        try:
            ss_id = vsp.GetSubSurf(wing_id, i)
            ss_type = int(vsp.GetSubSurfType(ss_id))
        except Exception:
            continue
        if ss_type != ss_control_const:
            continue
        name = vsp.GetSubSurfName(ss_id) if hasattr(vsp, "GetSubSurfName") else f"cs_{i}"

        def _pf(*parm_names: str) -> Optional[float]:
            for parm_name in parm_names:
                for group in ("SS_Control", "SS_Control_1", "SubSurface_1", "SubSurface"):
                    try:
                        pid = vsp.FindParm(ss_id, parm_name, group)
                        if pid:
                            return float(vsp.GetParmVal(pid))
                    except Exception:
                        continue
            return None

        eta_start = _pf("EtaStart", "Eta_Start")
        eta_end = _pf("EtaEnd", "Eta_End")
        u_start = _pf("UStart", "U_Start")
        u_end = _pf("UEnd", "U_End")
        c_start = _pf("Length_C_Start")
        c_end = _pf("Length_C_End")
        le_flag = _pf("LE_Flag")
        surf_type = _pf("Surf_Type")
        eta_flag = _pf("EtaFlag", "Eta_Flag")

        # Prefer Eta if EtaFlag truthy; else fall back to U.
        prefer_eta = bool(eta_flag) or (eta_start is not None and eta_end is not None)
        span_start = eta_start if prefer_eta else u_start
        span_end = eta_end if prefer_eta else u_end

        # Clamp to avoid VSP parametric singularity.
        if span_start is not None:
            span_start = min(max(span_start, _ETA_CLAMP_LO), _ETA_CLAMP_HI)
        if span_end is not None:
            span_end = min(max(span_end, _ETA_CLAMP_LO), _ETA_CLAMP_HI)

        out.append({
            "name": name,
            "type": _classify_control_name(name),
            "eta_start": span_start,
            "eta_end": span_end,
            "chord_fraction_start": c_start,
            "chord_fraction_end": c_end,
            "edge": "leading" if (le_flag or 0) > 0.5 else "trailing",
            "surf_type": {0: "upper", 1: "lower", 2: "both"}.get(
                int(surf_type) if surf_type is not None else 2, "both"
            ),
        })
    return out


# ---------------------------------------------------------------------------
# Dihedral schedule & segment scaling (Phase 2)
# ---------------------------------------------------------------------------


def _extract_dihedral_schedule(
    schedule: Sequence[Dict[str, float]],
) -> List[List[float]]:
    """Accumulate ``[[y, z], ...]`` from per-segment dihedral.

    Phase 1's ``schedule`` already lists per-station y/chord/dihedral.
    The dihedral on station i is the *outboard segment's* angle (i.e.
    applies from station i-1 to station i).  For station 0 we use 0.
    """
    if not schedule:
        return []
    out: List[List[float]] = [[0.0, 0.0]]
    prev_y = float(schedule[0]["y"])
    z_accum = 0.0
    for i in range(1, len(schedule)):
        y_i = float(schedule[i]["y"])
        dih_deg = float(schedule[i].get("dihedral_deg", 0.0) or 0.0)
        dy = y_i - prev_y
        z_accum += dy * math.sin(math.radians(dih_deg))
        out.append([y_i, z_accum])
        prev_y = y_i
    return out


def _scale_segments(
    template_segments: Sequence[float],
    template_half_span: float,
    new_half_span: float,
    tolerance_m: float = 1.0e-3,
) -> List[float]:
    """Proportionally scale spar-segment lengths to a new half-span.

    Raises ``ValueError`` if the resulting total departs from
    ``new_half_span`` by more than ``tolerance_m`` (which would indicate
    a bug rather than a floating-point roundoff).
    """
    if template_half_span <= 0:
        raise ValueError("template_half_span must be positive")
    if new_half_span <= 0:
        raise ValueError("new_half_span must be positive")
    if not template_segments:
        return []
    k = float(new_half_span) / float(template_half_span)
    scaled = [float(s) * k for s in template_segments]
    err = abs(sum(scaled) - float(new_half_span))
    if err > tolerance_m:
        raise ValueError(
            f"_scale_segments tolerance exceeded: sum={sum(scaled):.6f} "
            f"vs target={new_half_span:.6f} (err={err:.6f} > {tolerance_m})"
        )
    return scaled


# ---------------------------------------------------------------------------
# Internal helpers — wing / XSec data
# ---------------------------------------------------------------------------


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


def summarize_vsp_surfaces(
    vsp_path: str | Path,
    *,
    airfoil_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Read a .vsp3 and return a dict describing its main wing + empennage.

    Parameters
    ----------
    vsp_path : str | Path
        Path to ``.vsp3`` file.
    airfoil_dir : str | Path, optional
        Directory of Selig ``.dat`` files.  When provided, FILE_AIRFOIL
        cross-sections are matched against on-disk ``.dat`` files by
        maximum thickness-to-chord ratio (Phase 2).

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

    airfoil_dir_p = Path(airfoil_dir) if airfoil_dir is not None else None

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
        airfoils = _extract_airfoil_refs(vsp, gid, sched, airfoil_dir=airfoil_dir_p)
        controls = _extract_controls(vsp, gid)
        dihedral_schedule = _extract_dihedral_schedule(sched)
        geoms.append({
            "id": gid,
            "name": name,
            "name_norm": _norm(name),
            "schedule": sched,
            "airfoils": airfoils,
            "controls": controls,
            "dihedral_schedule": dihedral_schedule,
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
        "airfoils": list(g.get("airfoils", [])),
        "controls": list(g.get("controls", [])),
        "dihedral_schedule": list(g.get("dihedral_schedule", [])),
    }


def _log_summary(result: Dict[str, Any]) -> None:
    for kind in ("main_wing", "horizontal_tail", "vertical_fin"):
        entry = result[kind]
        if entry is None:
            logger.info("VSP introspect: %s not detected", kind)
            continue
        n_ctl = len(entry.get("controls", []))
        n_afl = len(entry.get("airfoils", []))
        logger.info(
            "VSP introspect: %s = %s  span=%.3f m  root=%.4f m  tip=%.4f m  "
            "airfoils=%d  controls=%d",
            kind,
            entry["name"],
            entry["span_m"],
            entry["root_chord_m"],
            entry["tip_chord_m"],
            n_afl,
            n_ctl,
        )


def _pick_endpoint_airfoil_refs(
    refs: Sequence[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not refs:
        return None, None
    ordered = sorted(refs, key=lambda ref: float(ref.get("station_y", 0.0)))
    return ordered[0], ordered[-1]


def _airfoil_name_exists_in_dir(name: str, airfoil_dir: str | Path) -> bool:
    af_dir = Path(airfoil_dir)
    if not af_dir.is_dir():
        return False

    raw = Path(str(name))
    candidates = {
        str(name),
        raw.name,
        raw.stem,
        raw.stem.lower(),
        raw.stem.upper(),
    }
    for candidate in candidates:
        path = af_dir / candidate
        if path.is_file():
            return True
        if not Path(candidate).suffix:
            if (af_dir / f"{candidate}.dat").is_file():
                return True
            if (af_dir / f"{candidate}.DAT").is_file():
                return True
    return False


def _merge_main_wing_airfoils(
    wing_cfg: Dict[str, Any],
    airfoil_refs: Sequence[Dict[str, Any]],
    airfoil_dir: Optional[str | Path],
) -> None:
    root_ref, tip_ref = _pick_endpoint_airfoil_refs(airfoil_refs)
    for side, ref in (("root", root_ref), ("tip", tip_ref)):
        if ref is None:
            continue
        tc = ref.get("thickness_tc")
        if tc is not None and math.isfinite(float(tc)) and float(tc) > 0.0:
            wing_cfg[f"airfoil_{side}_tc"] = float(tc)

        name = ref.get("name")
        if not name:
            continue
        source = str(ref.get("source", ""))
        use_vsp_name = source != "afile" or airfoil_dir is None
        if source == "afile" and airfoil_dir is not None:
            use_vsp_name = _airfoil_name_exists_in_dir(str(name), airfoil_dir)
        if use_vsp_name:
            wing_cfg[f"airfoil_{side}"] = str(name)
            continue

        logger.warning(
            "Preserving template wing.airfoil_%s=%s because VSP AFILE %s "
            "was not found under io.airfoil_dir=%s",
            side,
            wing_cfg.get(f"airfoil_{side}"),
            name,
            airfoil_dir,
        )


def merge_into_config_dict(
    base_cfg_dict: Dict[str, Any],
    summary: Dict[str, Any],
    *,
    scale_segments: bool = True,
    template_half_span: Optional[float] = None,
) -> Dict[str, Any]:
    """Non-destructively override wing / empennage geometry from VSP summary.

    Only geometry fields are touched; engineering fields (materials,
    safety factors, solver, spar segments) are left exactly as in the
    base config — except that ``main_spar.segments`` and
    ``rear_spar.segments`` are proportionally rescaled when
    ``scale_segments=True`` and the new half-span differs from the
    template's.

    Parameters
    ----------
    base_cfg_dict : dict
        Template config (nested dict from yaml.safe_load).
    summary : dict
        Output of :func:`summarize_vsp_surfaces`.
    scale_segments : bool, default True
        When True (default), proportionally rescale spar segment lengths
        to the new half-span.  Disabling is useful when the template
        segments were already tuned for the new aircraft.
    template_half_span : float, optional
        Override for the template's half-span.  When ``None`` we infer
        it from ``sum(main_spar.segments)``.

    Returns
    -------
    dict  — a new dict; the input is never mutated.
    """
    out: Dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v)
        for k, v in base_cfg_dict.items()
    }

    mw = summary.get("main_wing")
    new_half_span: Optional[float] = None
    if mw is not None:
        out.setdefault("wing", {})
        out["wing"]["span"] = float(mw["span_m"])
        out["wing"]["root_chord"] = float(mw["root_chord_m"])
        out["wing"]["tip_chord"] = float(mw["tip_chord_m"])
        new_half_span = float(mw["half_span_m"])
        # Continuous dihedral schedule — optional, for downstream consumers.
        dsched = mw.get("dihedral_schedule") or []
        if dsched:
            out["wing"]["dihedral_schedule"] = [
                [float(y), float(z)] for y, z in dsched
            ]
        _merge_main_wing_airfoils(
            out["wing"],
            mw.get("airfoils") or [],
            (out.get("io") or {}).get("airfoil_dir"),
        )

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

    # ── Segment auto-scaling ────────────────────────────────────────────
    if scale_segments and new_half_span is not None:
        for spar_key in ("main_spar", "rear_spar"):
            spar_cfg = out.get(spar_key) or {}
            segments = spar_cfg.get("segments") or []
            if not segments:
                continue
            tmpl_half = (
                template_half_span
                if template_half_span is not None
                else float(sum(segments))
            )
            if tmpl_half <= 0 or abs(tmpl_half - new_half_span) < 1e-6:
                # Nothing to do: either can't infer or already matches.
                continue
            try:
                scaled = _scale_segments(segments, tmpl_half, new_half_span)
            except ValueError as exc:
                logger.warning(
                    "Skipping segment auto-scale for %s: %s", spar_key, exc
                )
                continue
            logger.info(
                "Scaled %s.segments: %s → %s (half-span %.3f → %.3f m)",
                spar_key,
                ["%.3f" % s for s in segments],
                ["%.3f" % s for s in scaled],
                tmpl_half,
                new_half_span,
            )
            out[spar_key] = {**spar_cfg, "segments": scaled}

    return out


__all__ = [
    "summarize_vsp_surfaces",
    "merge_into_config_dict",
    "_scale_segments",
    "_extract_dihedral_schedule",
    "_naca_four_series_name",
    "_classify_control_name",
]
