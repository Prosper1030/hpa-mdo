"""Generate a **cruise-shape** .vsp3 from jig geometry + structural deflections.

Pipeline role
-------------
The project's canonical aero→structure loop is::

    reference .vsp3 (jig, source of truth)
        │  VSPBuilder → wing section schedule
        ▼
    structural solve (OpenMDAO FEM in structure/oas_structural.py)
        │  nodal disp (nn, 6) = [ux, uy, uz, θx, θy, θz]
        ▼
    CruiseVSPBuilder                 ← this module
        │  • z_cruise(y) = z_jig(y) + uz(y)
        │  • twist_cruise(y) = twist_jig(y) + θy(y)  (rad → deg)
        │  • per-segment dihedral refit from atan2(Δz, Δy)
        ▼
    cruise.vsp3  →  CFD (STEP/STL via vsp_to_cfd.py)

Only the main wing is deformed.  Empennage surfaces are copied from the
jig schedule unchanged — their flexibility is outside the main-spar
optimisation scope in the current problem statement.

Error philosophy: like VSPBuilder this never crashes; on failure it logs
``val_weight: 99999`` and returns a failure dict.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np

from hpa_mdo.aero.vsp_builder import VSPBuilder, _airfoil_for_eta, _failure_dict
from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)


class CruiseVSPBuilder:
    """Warp a jig-shape wing schedule by a structural displacement field.

    Parameters
    ----------
    cfg : HPAConfig
        Same config used for the structural solve.  ``cfg.io.vsp_model``
        (resolved via ``sync_root``) is consulted for the jig schedule.
    y_samples_m : array-like
        Half-span spanwise stations (monotone, y≥0) where displacements
        are sampled.  Typically the OpenMDAO FEM node coordinates.
    uz_samples_m : array-like
        Flapwise deflection in metres at each y_samples station
        (+z = lift direction).  Length must match y_samples.
    twist_samples_rad : array-like
        Nose-up torsional rotation θy in radians at each station.
        Sign convention matches ``structure/fem/assembly.py`` disp[:, 4].
    """

    def __init__(
        self,
        cfg: HPAConfig,
        y_samples_m: Sequence[float],
        uz_samples_m: Sequence[float],
        twist_samples_rad: Sequence[float],
    ):
        self.cfg = cfg
        y = np.asarray(y_samples_m, dtype=float)
        uz = np.asarray(uz_samples_m, dtype=float)
        tw = np.asarray(twist_samples_rad, dtype=float)
        if y.shape != uz.shape or y.shape != tw.shape:
            raise ValueError(
                f"y/uz/twist must share shape: got {y.shape}, {uz.shape}, {tw.shape}"
            )
        if y.size < 2:
            raise ValueError("need at least two spanwise samples")

        order = np.argsort(y)
        self._y = y[order]
        self._uz = uz[order]
        self._twist_deg = np.degrees(tw[order])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, output_path: str | Path) -> Dict[str, Any]:
        """Write cruise .vsp3 to *output_path*.  Returns payload dict."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            import openvsp as vsp  # type: ignore
        except ImportError:
            return _failure_dict(
                "openvsp not importable — cannot build cruise .vsp3"
            )

        try:
            jig_schedule = self._jig_schedule(vsp)
            cruise_schedule = self._deform_schedule(jig_schedule)
            self._write_vsp(vsp, cruise_schedule, out)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("CruiseVSPBuilder failure")
            return _failure_dict(f"cruise build error: {exc}")

        return {
            "success": True,
            "vsp3_path": str(out),
            "n_stations": len(cruise_schedule),
            "tip_z_m": cruise_schedule[-1]["z_m"],
            "tip_twist_deg": cruise_schedule[-1]["twist_deg"],
        }

    # ------------------------------------------------------------------
    # Schedule pipeline
    # ------------------------------------------------------------------

    def _jig_schedule(self, vsp: Any) -> List[Dict[str, Any]]:
        """Get the jig-shape schedule.  Reference VSP preferred."""
        builder = VSPBuilder(self.cfg)
        schedule = builder._wing_section_schedule(vsp=vsp)
        if len(schedule) < 2:
            raise RuntimeError(
                "jig wing schedule has <2 stations — check reference VSP and config"
            )
        # Ensure each station has a z_m field (VSPBuilder only populates
        # z_m when the dihedral multiplier != 1; for cruise we need them).
        if "z_m" not in schedule[0]:
            z = 0.0
            schedule[0]["z_m"] = 0.0
            for i in range(1, len(schedule)):
                dy = float(schedule[i]["y"]) - float(schedule[i - 1]["y"])
                local_dih = float(
                    schedule[i].get(
                        "segment_dihedral_deg",
                        0.5 * (
                            float(schedule[i - 1]["dihedral_deg"])
                            + float(schedule[i]["dihedral_deg"])
                        ),
                    )
                )
                z += dy * math.tan(math.radians(local_dih))
                schedule[i]["z_m"] = z
        return schedule

    def _deform_schedule(
        self, jig_schedule: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Apply uz/twist interpolation to produce the cruise schedule."""
        y_arr = np.asarray([float(s["y"]) for s in jig_schedule], dtype=float)
        uz_at = np.interp(y_arr, self._y, self._uz)
        twist_at = np.interp(y_arr, self._y, self._twist_deg)

        cruise: List[Dict[str, Any]] = []
        for i, src in enumerate(jig_schedule):
            entry = dict(src)
            entry["z_m"] = float(src["z_m"]) + float(uz_at[i])
            entry["twist_deg"] = float(twist_at[i])
            cruise.append(entry)

        # Refit per-segment dihedral from the deformed z profile.
        for i in range(1, len(cruise)):
            dy = cruise[i]["y"] - cruise[i - 1]["y"]
            if dy <= 1.0e-9:
                continue
            dz = cruise[i]["z_m"] - cruise[i - 1]["z_m"]
            dih = math.degrees(math.atan2(dz, dy))
            cruise[i]["segment_dihedral_deg"] = dih
            cruise[i]["dihedral_deg"] = dih
        cruise[0]["dihedral_deg"] = cruise[1]["dihedral_deg"]

        logger.info(
            "Cruise shape: tip z %.3f m (jig %.3f m), tip twist %+.3f deg",
            cruise[-1]["z_m"],
            jig_schedule[-1]["z_m"],
            cruise[-1]["twist_deg"],
        )
        return cruise

    # ------------------------------------------------------------------
    # VSP output
    # ------------------------------------------------------------------

    def _write_vsp(
        self,
        vsp: Any,
        schedule: List[Dict[str, Any]],
        output: Path,
    ) -> None:
        """Mirror VSPBuilder._build_with_api but stamp per-XSec Twist."""
        w = self.cfg.wing
        vsp.ClearVSPModel()

        wing_id = vsp.AddGeom("WING")
        vsp.SetGeomName(wing_id, "MainWing_Cruise")

        xsec_surf = vsp.GetXSecSurf(wing_id, 0)
        n_segments = len(schedule) - 1
        for _ in range(n_segments - 1):
            vsp.InsertXSec(wing_id, 1, vsp.XS_FOUR_SERIES)

        # Root XSec (index 0).
        builder = VSPBuilder(self.cfg)
        builder._assign_airfoil_api(vsp, xsec_surf, 0, schedule[0]["airfoil"])
        root_twist = schedule[0].get("twist_deg", 0.0)
        try:
            vsp.SetParmVal(vsp.GetXSecParm(vsp.GetXSec(xsec_surf, 0), "Twist"), root_twist)
        except Exception:
            pass  # root XSec may not expose Twist parm — ignore

        for seg_idx in range(n_segments):
            out_idx = seg_idx + 1
            inboard = schedule[seg_idx]
            outboard = schedule[seg_idx + 1]
            seg_span = outboard["y"] - inboard["y"]

            xs = vsp.GetXSec(xsec_surf, out_idx)
            vsp.SetDriverGroup(
                wing_id,
                out_idx,
                vsp.SPAN_WSECT_DRIVER,
                vsp.ROOTC_WSECT_DRIVER,
                vsp.TIPC_WSECT_DRIVER,
            )
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Root_Chord"), inboard["chord"])
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Tip_Chord"), outboard["chord"])
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Span"), seg_span)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Sweep"), 0.0)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Sweep_Location"), w.spar_location_xc)
            vsp.SetParmVal(
                vsp.GetXSecParm(xs, "Dihedral"),
                outboard.get("segment_dihedral_deg", outboard["dihedral_deg"]),
            )
            try:
                vsp.SetParmVal(
                    vsp.GetXSecParm(xs, "Twist"),
                    outboard.get("twist_deg", 0.0),
                )
            except Exception:
                pass
            vsp.Update()

            builder._assign_airfoil_api(vsp, xsec_surf, out_idx, outboard["airfoil"])

        vsp.SetParmVal(
            vsp.FindParm(wing_id, "Sym_Planar_Flag", "Sym"),
            vsp.SYM_XZ,
        )

        # Empennage copied through unchanged (rigid in this pipeline).
        builder._add_lifting_surface_api(vsp, self.cfg.horizontal_tail)
        builder._add_lifting_surface_api(vsp, self.cfg.vertical_fin)

        vsp.Update()
        vsp.WriteVSPFile(str(output))
        logger.info(
            "Wrote cruise .vsp3: %s (%d segments)", output, n_segments
        )


__all__ = ["CruiseVSPBuilder"]
