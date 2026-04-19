"""Generate OpenVSP geometry from HPAConfig and optionally run VSPAero.

Workflow:
    1. Instantiate VSPBuilder with an HPAConfig object.
    2. Call build_vsp3() to write a .vsp3 file via the OpenVSP Python API.
    3. Call run_vspaero() to execute a VLM/panel sweep over specified AoA list.
    4. Or use build_and_run() as a single convenience entry-point.

If the ``openvsp`` package is not installed the builder falls back to
generating a ``.vspscript`` text file that can be executed inside the
OpenVSP GUI (File -> Run Script).

Error philosophy — **never crash**:
    * Every OpenVSP / subprocess call is wrapped in try/except.
    * On any failure the builder logs ``val_weight: 99999`` (the
      sentinel understood by the optimiser loop) and returns a failure
      dict so the caller can inspect ``result["success"]``.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from hpa_mdo.aero.vsp_introspect import _extract_airfoil_refs
from hpa_mdo.core.config import HPAConfig, LiftingSurfaceConfig
from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)

# Sentinel logged on ANY failure so the optimiser does not hang.
_FAILURE_WEIGHT = 99999

# Default timeout for VSPAero subprocess (seconds).
_VSPAERO_TIMEOUT = 600
_VSPAERO_ANALYSIS_METHOD_CODES = {
    "vlm": 0,
    "panel": 1,
}
_VSPAERO_ANALYSIS_METHOD_NAMES = {
    code: name for name, code in _VSPAERO_ANALYSIS_METHOD_CODES.items()
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_openvsp() -> bool:
    """Return True if the openvsp Python module is importable."""
    try:
        import openvsp  # noqa: F401

        return True
    except ImportError:
        return False


def _failure_dict(msg: str) -> Dict[str, Any]:
    """Return a standardised failure payload and log the sentinel."""
    logger.warning("val_weight: %s", _FAILURE_WEIGHT)
    logger.error("VSPBuilder failure: %s", msg)
    return {
        "success": False,
        "error": msg,
        "vsp3_path": None,
        "lod_path": None,
        "polar_path": None,
    }


def _resolve_vspaero_binary() -> str | None:
    """Return the available ``vspaero`` binary path, including packaged installs."""
    direct = shutil.which("vspaero")
    if direct is not None:
        return direct

    try:
        import openvsp  # type: ignore
    except ImportError:
        return None

    package_dir = Path(openvsp.__file__).resolve().parent
    for candidate_name in ("vspaero", "vspaero_opt"):
        candidate = package_dir / candidate_name
        if candidate.is_file():
            return str(candidate)
    return None


def _normalize_vspaero_analysis_method(value: str | int) -> tuple[str, int]:
    """Normalize user-facing VSPAero analysis method labels/codes."""
    if isinstance(value, int):
        if value not in _VSPAERO_ANALYSIS_METHOD_NAMES:
            raise ValueError(
                "vspaero_analysis_method must be one of "
                f"{tuple(_VSPAERO_ANALYSIS_METHOD_NAMES)}."
            )
        return _VSPAERO_ANALYSIS_METHOD_NAMES[value], int(value)

    text = str(value).strip().lower()
    if text.isdigit():
        return _normalize_vspaero_analysis_method(int(text))
    if text not in _VSPAERO_ANALYSIS_METHOD_CODES:
        raise ValueError(
            "vspaero_analysis_method must be one of "
            f"{tuple(_VSPAERO_ANALYSIS_METHOD_CODES)}."
        )
    return text, _VSPAERO_ANALYSIS_METHOD_CODES[text]


def _progressive_dihedral_deg(
    eta: float,
    dihedral_root_deg: float,
    dihedral_tip_deg: float,
    exponent: float,
) -> float:
    """Compute local dihedral angle at normalized span coordinate *eta* ∈ [0, 1].

    The formula is::

        dihedral(eta) = root + (tip - root) * eta^exponent

    With exponent=1 this gives a linear ramp; exponent=2 a quadratic ramp
    that concentrates dihedral outboard.
    """
    eta = max(0.0, min(float(eta), 1.0))
    return float(dihedral_root_deg) + (
        float(dihedral_tip_deg) - float(dihedral_root_deg)
    ) * (eta ** float(exponent))


def _airfoil_for_eta(cfg: HPAConfig, eta: float) -> str:
    """Return the config fallback airfoil choice at normalized span *eta*."""
    return cfg.wing.airfoil_root if eta < 0.5 else cfg.wing.airfoil_tip


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class VSPBuilder:
    """Build OpenVSP wing geometry from an HPAConfig and run VSPAero.

    Parameters
    ----------
    cfg : HPAConfig
        Fully-loaded configuration (see ``hpa_mdo.core.config``).
    vspaero_timeout : int
        Maximum seconds to wait for VSPAero to finish.  Default 600.
    """

    def __init__(
        self,
        cfg: HPAConfig,
        vspaero_timeout: int = _VSPAERO_TIMEOUT,
        *,
        dihedral_multiplier: float = 1.0,
        dihedral_exponent: float | None = None,
        vspaero_analysis_method: str | int = "vlm",
    ):
        self.cfg = cfg
        self.vspaero_timeout = vspaero_timeout
        if dihedral_multiplier < 0.0:
            raise ValueError("dihedral_multiplier must be >= 0.0")
        self.dihedral_multiplier = float(dihedral_multiplier)
        self.dihedral_exponent = (
            float(cfg.wing.dihedral_scaling_exponent)
            if dihedral_exponent is None
            else float(dihedral_exponent)
        )
        if self.dihedral_exponent < 0.0:
            raise ValueError("dihedral_exponent must be >= 0.0")
        (
            self.vspaero_analysis_method,
            self.vspaero_analysis_method_code,
        ) = _normalize_vspaero_analysis_method(vspaero_analysis_method)

    def _vspaero_geom_set_values(self, vsp: Any) -> tuple[int, int]:
        """Return the thick/thin geometry-set selection for the requested solver mode."""
        if self.vspaero_analysis_method == "panel":
            return int(vsp.SET_ALL), int(vsp.SET_NONE)
        return int(vsp.SET_NONE), int(vsp.SET_ALL)

    def _apply_vspaero_settings_container_api(self, vsp: Any) -> None:
        """Persist the requested VSPAero thick/thin geometry mode on the model settings."""
        try:
            settings_id = vsp.FindContainer("VSPAEROSettings", 0)
            if not settings_id:
                return
            geom_set, thin_geom_set = self._vspaero_geom_set_values(vsp)
            geom_parm = vsp.FindParm(settings_id, "GeomSet", "VSPAERO")
            thin_parm = vsp.FindParm(settings_id, "ThinGeomSet", "VSPAERO")
            if geom_parm:
                vsp.SetParmVal(geom_parm, geom_set)
            if thin_parm:
                vsp.SetParmVal(thin_parm, thin_geom_set)
            vsp.Update()
        except Exception:
            logger.warning(
                "Could not persist VSPAero %s mode onto VSPAEROSettings",
                self.vspaero_analysis_method,
            )

    def _apply_vspaero_geometry_mode_to_analysis(self, vsp: Any, analysis_name: str) -> None:
        """Apply the requested VLM/panel geometry mode to an Analysis Manager entry."""
        geom_set, thin_geom_set = self._vspaero_geom_set_values(vsp)
        names = set(vsp.GetAnalysisInputNames(analysis_name))
        if "GeomSet" in names:
            vsp.SetIntAnalysisInput(analysis_name, "GeomSet", [geom_set])
        if "ThinGeomSet" in names:
            vsp.SetIntAnalysisInput(analysis_name, "ThinGeomSet", [thin_geom_set])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_vsp3(self, output_path: str) -> Path:
        """Generate a ``.vsp3`` file from config parameters.

        If the ``openvsp`` module is available the native Python API is
        used; otherwise a ``.vspscript`` text file is written to the same
        directory and the method returns the path to that script.

        Returns
        -------
        Path
            Absolute path to the generated ``.vsp3`` (or ``.vspscript``).
        """
        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        if _has_openvsp():
            return self._build_with_api(output)
        else:
            logger.warning("openvsp Python module not found — generating .vspscript fallback.")
            script_path = output.with_suffix(".vspscript")
            return self._build_vspscript_fallback(script_path, output)

    def run_vspaero(
        self,
        vsp3_path: str,
        aoa_list: List[float],
        output_dir: str,
    ) -> Dict[str, Any]:
        """Run VSPAero analysis on an existing ``.vsp3`` file.

        Tries the OpenVSP Python API first; falls back to the ``vspaero``
        CLI executable.

        Parameters
        ----------
        vsp3_path : str
            Path to the ``.vsp3`` geometry file.
        aoa_list : list[float]
            Angles of attack to sweep [deg].
        output_dir : str
            Directory for VSPAero output files.

        Returns
        -------
        dict
            ``success``, ``lod_path``, ``polar_path``, ``error`` keys.
        """
        vsp3 = Path(vsp3_path).resolve()
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        if not vsp3.exists():
            return _failure_dict(f"vsp3 file not found: {vsp3}")

        # Try the OpenVSP Python API route first.
        if _has_openvsp():
            return self._run_vspaero_api(vsp3, aoa_list, out_dir)

        # Fall back to the CLI binary.
        return self._run_vspaero_cli(vsp3, aoa_list, out_dir)

    def build_and_run(
        self,
        output_dir: str,
        aoa_list: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Convenience: build geometry + run analysis in one call.

        Parameters
        ----------
        output_dir : str
            Root directory for the ``.vsp3`` and VSPAero output files.
        aoa_list : list[float] | None
            Angles of attack [deg].  Defaults to ``[-2, 0, 2, 4, 6, 8]``.

        Returns
        -------
        dict
            Merged result with ``vsp3_path``, ``lod_path``, ``polar_path``,
            ``success`` and ``error`` keys.
        """
        if aoa_list is None:
            aoa_list = [-2.0, 0.0, 2.0, 4.0, 6.0, 8.0]

        out = Path(output_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)

        vsp3_filename = self.cfg.project_name.replace(" ", "_").lower() + ".vsp3"
        vsp3_path = out / vsp3_filename

        try:
            built_path = self.build_vsp3(str(vsp3_path))
        except Exception as exc:
            return _failure_dict(f"build_vsp3 raised: {exc}")

        # If the fallback produced a .vspscript instead of .vsp3 we
        # cannot run VSPAero automatically.
        if built_path.suffix == ".vspscript":
            logger.info(
                "Generated .vspscript at %s — manual execution required.",
                built_path,
            )
            return {
                "success": True,
                "vsp3_path": None,
                "vspscript_path": str(built_path),
                "lod_path": None,
                "polar_path": None,
                "analysis_method": self.vspaero_analysis_method,
                "solver_backend": "manual_vspscript",
                "note": "Manual execution of .vspscript required (openvsp not installed).",
            }

        try:
            result = self.run_vspaero(str(built_path), aoa_list, str(out))
        except Exception as exc:
            return _failure_dict(f"run_vspaero raised: {exc}")

        result["vsp3_path"] = str(built_path)
        return result

    # ------------------------------------------------------------------
    # OpenVSP Python API path
    # ------------------------------------------------------------------

    def _build_with_api(self, output: Path) -> Path:
        """Use ``import openvsp as vsp`` to create the .vsp3 file.

        The main wing is built with **multiple segments** matching the
        spar segment layout, each carrying its own local dihedral angle
        to represent the progressive dihedral schedule from config.
        """
        try:
            import openvsp as vsp
        except ImportError:
            raise RuntimeError("openvsp is not available")

        w = self.cfg.wing
        schedule = self._wing_section_schedule(vsp=vsp)

        try:
            vsp.ClearVSPModel()

            # ── Create wing component ────────────────────────────────
            wing_id = vsp.AddGeom("WING")
            vsp.SetGeomName(wing_id, "MainWing")

            # OpenVSP wings default to one segment (2 XSecs, indices 0
            # and 1).  We need (len(schedule) - 1) segments, so insert
            # additional XSecs.
            xsec_surf = vsp.GetXSecSurf(wing_id, 0)
            n_segments = len(schedule) - 1
            for _ in range(n_segments - 1):
                vsp.InsertXSec(wing_id, 1, vsp.XS_FOUR_SERIES)

            # Assign airfoil on root XSec (index 0) — this is the
            # inboard XSec and does not carry segment driver parms.
            self._assign_airfoil_api(vsp, xsec_surf, 0, schedule[0]["airfoil"])

            # Configure each segment via its outboard XSec.
            for seg_idx in range(n_segments):
                outboard_xsec_idx = seg_idx + 1
                inboard = schedule[seg_idx]
                outboard = schedule[seg_idx + 1]
                seg_span = outboard["y"] - inboard["y"]

                xs = vsp.GetXSec(xsec_surf, outboard_xsec_idx)
                vsp.SetDriverGroup(
                    wing_id,
                    outboard_xsec_idx,
                    vsp.SPAN_WSECT_DRIVER,
                    vsp.ROOTC_WSECT_DRIVER,
                    vsp.TIPC_WSECT_DRIVER,
                )
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Root_Chord"), inboard["chord"])
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Tip_Chord"), outboard["chord"])
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Span"), seg_span)
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Sweep"), 0.0)
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Sweep_Location"), w.spar_location_xc)

                # OpenVSP applies the segment dihedral as a constant
                # angle across the segment span.  Reference-VSP schedules
                # carry this directly; config-derived schedules store
                # station angles and use the trapezoid average.
                local_dih = outboard.get(
                    "segment_dihedral_deg",
                    0.5 * (inboard["dihedral_deg"] + outboard["dihedral_deg"]),
                )
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Dihedral"), local_dih)
                vsp.Update()

                # Assign airfoil on the outboard XSec.
                self._assign_airfoil_api(vsp, xsec_surf, outboard_xsec_idx, outboard["airfoil"])

            logger.info(
                "MainWing: %d segments from %s",
                n_segments, schedule[0].get("source", "config"),
            )

            # ── Symmetry (full wing from half definition) ────────────
            vsp.SetParmVal(
                vsp.FindParm(wing_id, "Sym_Planar_Flag", "Sym"),
                vsp.SYM_XZ,
            )

            self._add_lifting_surface_api(vsp, self.cfg.horizontal_tail)
            self._add_lifting_surface_api(vsp, self.cfg.vertical_fin)

            vsp.Update()
            self._apply_vspaero_settings_container_api(vsp)

            # ── Save ─────────────────────────────────────────────────
            vsp.WriteVSPFile(str(output))
            logger.info("Wrote .vsp3 via API: %s", output)

        except Exception:
            # Last-resort safety net — do NOT propagate.
            logger.exception("OpenVSP API error during build")
            script_fb = output.with_suffix(".vspscript")
            logger.info("Falling back to .vspscript at %s", script_fb)
            return self._build_vspscript_fallback(script_fb, output)

        return output

    def _add_lifting_surface_api(self, vsp: Any, surface: LiftingSurfaceConfig) -> None:
        """Add a simple OpenVSP wing-like lifting surface from config."""
        if not surface.enabled:
            return

        geom_id = vsp.AddGeom("WING")
        vsp.SetGeomName(geom_id, surface.name)
        self._try_set_geom_parm(vsp, geom_id, ("X_Rel_Location", "X_Location"), surface.x_location)
        self._try_set_geom_parm(vsp, geom_id, ("Y_Rel_Location", "Y_Location"), surface.y_location)
        self._try_set_geom_parm(vsp, geom_id, ("Z_Rel_Location", "Z_Location"), surface.z_location)
        self._try_set_geom_parm(
            vsp, geom_id, ("X_Rel_Rotation", "X_Rotation"), surface.x_rotation_deg
        )
        self._try_set_geom_parm(
            vsp, geom_id, ("Y_Rel_Rotation", "Y_Rotation"), surface.y_rotation_deg
        )
        self._try_set_geom_parm(
            vsp, geom_id, ("Z_Rel_Rotation", "Z_Rotation"), surface.z_rotation_deg
        )

        xsec_surf = vsp.GetXSecSurf(geom_id, 0)
        root_xs = vsp.GetXSec(xsec_surf, 0)
        tip_xs = vsp.GetXSec(xsec_surf, 1)
        # All segment drivers live on the outboard XSec (index 1).
        vsp.SetDriverGroup(
            geom_id,
            1,
            vsp.SPAN_WSECT_DRIVER,
            vsp.ROOTC_WSECT_DRIVER,
            vsp.TIPC_WSECT_DRIVER,
        )
        vsp.SetParmVal(vsp.GetXSecParm(tip_xs, "Root_Chord"), surface.root_chord)
        vsp.SetParmVal(vsp.GetXSecParm(tip_xs, "Tip_Chord"), surface.tip_chord)
        vsp.SetParmVal(vsp.GetXSecParm(tip_xs, "Span"), self._vsp_surface_span(surface))
        vsp.SetParmVal(vsp.GetXSecParm(tip_xs, "Sweep"), 0.0)
        vsp.SetParmVal(vsp.GetXSecParm(tip_xs, "Sweep_Location"), 0.25)
        vsp.Update()

        self._assign_airfoil_api(vsp, xsec_surf, 0, surface.airfoil)
        self._assign_airfoil_api(vsp, xsec_surf, 1, surface.airfoil)

        sym_flag = vsp.SYM_XZ if surface.symmetry == "xz" else 0
        vsp.SetParmVal(vsp.FindParm(geom_id, "Sym_Planar_Flag", "Sym"), sym_flag)

    @staticmethod
    def _try_set_geom_parm(vsp: Any, geom_id: str, names: tuple[str, ...], value: float) -> None:
        """Set the first available geometry parameter name, tolerating VSP version drift."""
        for name in names:
            try:
                parm_id = vsp.FindParm(geom_id, name, "XForm")
                if parm_id:
                    vsp.SetParmVal(parm_id, float(value))
                    return
            except Exception:
                continue
        logger.warning("Could not set OpenVSP XForm parameter %s on %s", names[0], geom_id)

    def _assign_airfoil_api(
        self,
        vsp: Any,
        xsec_surf: str,
        xsec_idx: int,
        airfoil_name: str,
    ) -> None:
        """Try to load an airfoil .dat file; fall back to NACA 4-series parameters."""
        xs = vsp.GetXSec(xsec_surf, xsec_idx)
        dat_path = self._resolve_airfoil_dat(airfoil_name)

        if dat_path is not None:
            try:
                vsp.ChangeXSecShape(xsec_surf, xsec_idx, vsp.XS_FILE_AIRFOIL)
                xs = vsp.GetXSec(xsec_surf, xsec_idx)
                vsp.ReadFileAirfoil(xs, str(dat_path))
                logger.info("Loaded airfoil %s from %s", airfoil_name, dat_path)
                return
            except Exception:
                logger.warning(
                    "Failed to load airfoil file %s — using NACA fallback",
                    dat_path,
                )

        # Fallback: parsed NACA 4-series when available, otherwise a HPA-like placeholder.
        try:
            vsp.ChangeXSecShape(xsec_surf, xsec_idx, vsp.XS_FOUR_SERIES)
            xs = vsp.GetXSec(xsec_surf, xsec_idx)
            camber, camber_loc, thick_chord = self._naca_4_series_params(airfoil_name)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "Camber"), camber)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "CamberLoc"), camber_loc)
            vsp.SetParmVal(vsp.GetXSecParm(xs, "ThickChord"), thick_chord)
        except Exception:
            logger.warning("Could not set NACA fallback for xsec %d", xsec_idx)

    # ------------------------------------------------------------------
    # VSPAero execution
    # ------------------------------------------------------------------

    def _run_vspaero_api(
        self,
        vsp3: Path,
        aoa_list: List[float],
        out_dir: Path,
    ) -> Dict[str, Any]:
        """Run VSPAero through the OpenVSP Python API."""
        try:
            import openvsp as vsp
        except ImportError:
            return _failure_dict("openvsp import failed in _run_vspaero_api")

        try:
            vsp.ClearVSPModel()
            vsp.ReadVSPFile(str(vsp3))
            vsp.Update()

            # ── DegenGeom (required before VSPAero) ──────────────────
            compute_geometry_name = "VSPAEROComputeGeometry"
            vsp.SetAnalysisInputDefaults(compute_geometry_name)
            self._apply_vspaero_geometry_mode_to_analysis(vsp, compute_geometry_name)
            vsp.ExecAnalysis(compute_geometry_name)

            # ── Configure solver ─────────────────────────────────────
            analysis_name = "VSPAEROSweep"
            vsp.SetAnalysisInputDefaults(analysis_name)
            self._apply_vspaero_geometry_mode_to_analysis(vsp, analysis_name)

            # Flight conditions.
            flt = self.cfg.flight
            vsp.SetDoubleAnalysisInput(analysis_name, "Vinf", [flt.velocity])
            vsp.SetDoubleAnalysisInput(analysis_name, "Rho", [flt.air_density])

            # Reference area — wing planform.
            w = self.cfg.wing
            s_ref = 0.5 * (w.root_chord + w.tip_chord) * w.span
            vsp.SetDoubleAnalysisInput(analysis_name, "Sref", [s_ref])
            vsp.SetDoubleAnalysisInput(analysis_name, "bref", [w.span])
            vsp.SetDoubleAnalysisInput(analysis_name, "cref", [0.5 * (w.root_chord + w.tip_chord)])

            # AoA sweep.
            vsp.SetDoubleAnalysisInput(analysis_name, "AlphaStart", [min(aoa_list)])
            vsp.SetDoubleAnalysisInput(analysis_name, "AlphaEnd", [max(aoa_list)])
            n_aoa = len(aoa_list)
            vsp.SetIntAnalysisInput(analysis_name, "AlphaNpts", [n_aoa])

            # ── Execute ──────────────────────────────────────────────
            results_id = vsp.ExecAnalysis(analysis_name)

            # ── Locate output files ──────────────────────────────────
            stem = vsp3.stem
            lod_path = self._find_output(out_dir, stem, ".lod") or self._find_output(
                vsp3.parent, stem, ".lod"
            )
            polar_path = self._find_output(out_dir, stem, ".polar") or self._find_output(
                vsp3.parent, stem, ".polar"
            )

            # VSPAero sometimes writes next to the .vsp3 — copy if needed.
            if lod_path and lod_path.parent != out_dir:
                dst = out_dir / lod_path.name
                shutil.copy2(lod_path, dst)
                lod_path = dst
            if polar_path and polar_path.parent != out_dir:
                dst = out_dir / polar_path.name
                shutil.copy2(polar_path, dst)
                polar_path = dst

            return {
                "success": True,
                "lod_path": str(lod_path) if lod_path else None,
                "polar_path": str(polar_path) if polar_path else None,
                "results_id": results_id,
                "analysis_method": self.vspaero_analysis_method,
                "solver_backend": "openvsp_api",
                "error": None,
            }

        except Exception as exc:
            return _failure_dict(f"VSPAero API execution failed: {exc}")

    def _run_vspaero_cli(
        self,
        vsp3: Path,
        aoa_list: List[float],
        out_dir: Path,
    ) -> Dict[str, Any]:
        """Run VSPAero via the command-line ``vspaero`` binary."""
        vspaero_bin = _resolve_vspaero_binary()
        if vspaero_bin is None:
            return _failure_dict(
                "vspaero binary not found (PATH or packaged openvsp install) and openvsp module unavailable"
            )

        # VSPAero CLI requires a DegenGeom CSV.  Generate it with the
        # lightweight vspscript approach if the API is unavailable.
        # The CLI expects a .vspaero setup file.
        stem = vsp3.stem
        setup_path = out_dir / f"{stem}.vspaero"

        w = self.cfg.wing
        flt = self.cfg.flight
        s_ref = 0.5 * (w.root_chord + w.tip_chord) * w.span
        c_ref = 0.5 * (w.root_chord + w.tip_chord)

        try:
            setup_lines = [
                f"Sref = {s_ref:.6f}",
                f"bref = {w.span:.6f}",
                f"cref = {c_ref:.6f}",
                f"Xref = {0.25 * w.root_chord:.6f}",
                "Yref = 0.000000",
                "Zref = 0.000000",
                f"Mach = {flt.velocity / 343.0:.6f}",
                f"AoA = {', '.join(f'{a:.2f}' for a in aoa_list)}",
                "Beta = 0.000000",
                f"Vinf = {flt.velocity:.4f}",
                f"Rho = {flt.air_density:.6f}",
                "ClMax = -1.000000",
                "MaxTurningAngle = -1.000000",
                "Symmetry = NO",
                "FarDist = -1.000000",
                "NumWakeNodes = -1",
                "WakeIters = 3",
            ]
            setup_path.write_text("\n".join(setup_lines) + "\n")

            cmd = [vspaero_bin, str(setup_path)]
            logger.info("Running VSPAero CLI: %s", " ".join(cmd))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.vspaero_timeout,
                cwd=str(out_dir),
            )

            if result.returncode != 0:
                return _failure_dict(
                    f"vspaero exited with code {result.returncode}: {result.stderr[:500]}"
                )

            lod_path = self._find_output(out_dir, stem, ".lod")
            polar_path = self._find_output(out_dir, stem, ".polar")

            return {
                "success": True,
                "lod_path": str(lod_path) if lod_path else None,
                "polar_path": str(polar_path) if polar_path else None,
                "analysis_method": self.vspaero_analysis_method,
                "solver_backend": "vspaero_cli",
                "error": None,
            }

        except subprocess.TimeoutExpired:
            return _failure_dict(f"vspaero timed out after {self.vspaero_timeout}s")
        except FileNotFoundError:
            return _failure_dict("vspaero binary disappeared from PATH")
        except Exception as exc:
            return _failure_dict(f"vspaero CLI failed: {exc}")

    # ------------------------------------------------------------------
    # .vspscript fallback
    # ------------------------------------------------------------------

    def _build_vspscript_fallback(self, script_path: Path, vsp3_target: Path) -> Path:
        """Write a VSPScript that recreates the wing geometry.

        The script uses multiple segments with progressive dihedral,
        matching the spar segment layout.

        Can be executed inside OpenVSP via File -> Run Script,
        or from the command line with ``vsp -script <file>``.
        """
        w = self.cfg.wing
        schedule = self._wing_section_schedule()
        n_segments = len(schedule) - 1

        tail_blocks = "\n".join(
            self._vspscript_lifting_surface_block(surface)
            for surface in (self.cfg.horizontal_tail, self.cfg.vertical_fin)
            if surface.enabled
        )

        # Build the multi-segment wing body.
        seg_lines: List[str] = []

        # Insert additional XSecs for segments beyond the default first one.
        for i in range(n_segments - 1):
            seg_lines.append(f'    InsertXSec( wing_id, 1, XS_FOUR_SERIES );')

        # Assign root airfoil (XSec index 0).
        root_af_block = self._vspscript_airfoil_block(
            xsec_idx=0,
            dat_path=self._resolve_airfoil_dat(schedule[0]["airfoil"]),
            label=schedule[0]["airfoil"],
        )
        seg_lines.append(textwrap.indent(root_af_block, "    "))

        # Configure each segment via its outboard XSec.
        for seg_idx in range(n_segments):
            outboard_idx = seg_idx + 1
            inboard = schedule[seg_idx]
            outboard = schedule[seg_idx + 1]
            seg_span = outboard["y"] - inboard["y"]
            local_dih = outboard.get(
                "segment_dihedral_deg",
                0.5 * (inboard["dihedral_deg"] + outboard["dihedral_deg"]),
            )

            seg_lines.append(f'    // ── Segment {seg_idx}: y={inboard["y"]:.1f}→{outboard["y"]:.1f} m, dih={local_dih:.2f}° ──')
            seg_lines.append(f'    string seg{seg_idx}_xs = GetXSec( xsec_surf, {outboard_idx} );')
            seg_lines.append(f'    SetDriverGroup( wing_id, {outboard_idx}, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER, TIPC_WSECT_DRIVER );')
            seg_lines.append(f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Root_Chord" ), {inboard["chord"]:.6f} );')
            seg_lines.append(f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Tip_Chord" ), {outboard["chord"]:.6f} );')
            seg_lines.append(f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Span" ), {seg_span:.6f} );')
            seg_lines.append(f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Sweep" ), 0.0 );')
            seg_lines.append(f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Sweep_Location" ), {w.spar_location_xc:.4f} );')
            seg_lines.append(f'    SetParmVal( GetXSecParm( seg{seg_idx}_xs, "Dihedral" ), {local_dih:.6f} );')
            seg_lines.append('    Update();')

            # Outboard XSec airfoil.
            af_block = self._vspscript_airfoil_block(
                xsec_idx=outboard_idx,
                dat_path=self._resolve_airfoil_dat(outboard["airfoil"]),
                label=outboard["airfoil"],
            )
            seg_lines.append(textwrap.indent(af_block, "    "))

        segment_body = "\n".join(seg_lines)

        script = textwrap.dedent(f"""\
            // ─────────────────────────────────────────────────────────────
            // VSPScript: {self.cfg.project_name} aircraft geometry
            // Generated by hpa_mdo.aero.vsp_builder (multi-segment mode)
            // ─────────────────────────────────────────────────────────────

            void main()
            {{
                // Clear existing model
                ClearVSPModel();

                // ── Create wing ({n_segments} segments, progressive dihedral) ──
                string wing_id = AddGeom( "WING" );
                SetGeomName( wing_id, "MainWing" );
                string xsec_surf = GetXSecSurf( wing_id, 0 );

            {textwrap.indent(segment_body, "    ")}

                // ── Symmetry (mirror about XZ plane for full wing) ──────
                string sym_parm = FindParm( wing_id, "Sym_Planar_Flag", "Sym" );
                SetParmVal( sym_parm, SYM_XZ );

            {textwrap.indent(tail_blocks, "    ")}

                Update();

                // ── Save ────────────────────────────────────────────────
                WriteVSPFile( "{str(vsp3_target).replace(chr(92), '/')}" );
                Print( "Saved: {vsp3_target.name}" );
            }}
        """)

        try:
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(script)
            logger.info("Wrote .vspscript fallback: %s (%d segments)", script_path, n_segments)
        except Exception as exc:
            # Even fallback writing failed — return failure but never crash.
            logger.warning("val_weight: %s", _FAILURE_WEIGHT)
            logger.error("Failed to write .vspscript: %s", exc)

        return script_path

    def _vspscript_lifting_surface_block(self, surface: LiftingSurfaceConfig) -> str:
        """Return a VSPScript block for a tail/fin wing-like lifting surface."""
        af_dat = self._resolve_airfoil_dat(surface.airfoil)
        surface_id = self._safe_script_identifier(surface.name)
        root_af_block = self._vspscript_airfoil_block(
            xsec_idx=0,
            dat_path=af_dat,
            label=surface.airfoil,
            xsec_surf_var=f"{surface_id}_surf",
            var_prefix=f"{surface_id}_",
        )
        tip_af_block = self._vspscript_airfoil_block(
            xsec_idx=1,
            dat_path=af_dat,
            label=surface.airfoil,
            xsec_surf_var=f"{surface_id}_surf",
            var_prefix=f"{surface_id}_",
        )
        sym_value = "SYM_XZ" if surface.symmetry == "xz" else "0"
        return textwrap.dedent(f"""\
            // ── {surface.name} ──────────────────────────────────────────
            string {surface_id}_id = AddGeom( "WING" );
            SetGeomName( {surface_id}_id, "{surface.name}" );
            SetParmVal( FindParm( {surface_id}_id, "X_Rel_Location", "XForm" ), {surface.x_location:.6f} );
            SetParmVal( FindParm( {surface_id}_id, "Y_Rel_Location", "XForm" ), {surface.y_location:.6f} );
            SetParmVal( FindParm( {surface_id}_id, "Z_Rel_Location", "XForm" ), {surface.z_location:.6f} );
            SetParmVal( FindParm( {surface_id}_id, "X_Rel_Rotation", "XForm" ), {surface.x_rotation_deg:.6f} );
            SetParmVal( FindParm( {surface_id}_id, "Y_Rel_Rotation", "XForm" ), {surface.y_rotation_deg:.6f} );
            SetParmVal( FindParm( {surface_id}_id, "Z_Rel_Rotation", "XForm" ), {surface.z_rotation_deg:.6f} );

            string {surface_id}_surf = GetXSecSurf( {surface_id}_id, 0 );
            string {surface_id}_root_xs = GetXSec( {surface_id}_surf, 0 );
            string {surface_id}_tip_xs = GetXSec( {surface_id}_surf, 1 );
            // Segment drivers live on the outboard XSec (index 1).
            SetDriverGroup( {surface_id}_id, 1, SPAN_WSECT_DRIVER, ROOTC_WSECT_DRIVER, TIPC_WSECT_DRIVER );
            SetParmVal( GetXSecParm( {surface_id}_tip_xs, "Root_Chord" ), {surface.root_chord:.6f} );
            SetParmVal( GetXSecParm( {surface_id}_tip_xs, "Tip_Chord" ), {surface.tip_chord:.6f} );
            SetParmVal( GetXSecParm( {surface_id}_tip_xs, "Span" ), {self._vsp_surface_span(surface):.6f} );
            SetParmVal( GetXSecParm( {surface_id}_tip_xs, "Sweep" ), 0.0 );
            SetParmVal( GetXSecParm( {surface_id}_tip_xs, "Sweep_Location" ), 0.25 );
            SetParmVal( GetXSecParm( {surface_id}_tip_xs, "Dihedral" ), 0.0 );
            Update();

        {textwrap.indent(root_af_block, "    ")}
        {textwrap.indent(tip_af_block, "    ")}
            SetParmVal( FindParm( {surface_id}_id, "Sym_Planar_Flag", "Sym" ), {sym_value} );
        """)

    @staticmethod
    def _safe_script_identifier(name: str) -> str:
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name)
        return cleaned.strip("_") or "surface"

    @staticmethod
    def _vsp_surface_span(surface: LiftingSurfaceConfig) -> float:
        if surface.symmetry == "xz":
            return 0.5 * float(surface.span)
        return float(surface.span)

    def _wing_section_schedule(self, vsp: Any | None = None) -> List[Dict[str, Any]]:
        """Return the list of wing section stations for VSP multi-segment construction.

        Each entry is a dict with keys:
            y            — spanwise station [m]
            chord        — local chord [m]
            dihedral_deg — local dihedral angle [deg]
            airfoil      — airfoil name (interpolated between root and tip)

        If ``cfg.io.vsp_model`` is available and the OpenVSP API is in
        use, its main-wing section schedule is treated as authoritative
        for CFD geometry fidelity.  The schedule is then densified at
        spar segment boundaries so structural joints remain explicit.
        If no reference VSP can be read, stations are generated from
        the config's spar segment boundaries and root/tip planform.
        """
        reference = self._reference_vsp_wing_section_schedule(vsp)
        if reference is not None:
            return self._apply_dihedral_multiplier_to_schedule(reference)
        return self._apply_dihedral_multiplier_to_schedule(self._config_wing_section_schedule())

    def _apply_dihedral_multiplier_to_schedule(
        self,
        schedule: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Apply AVL-style progressive z scaling and refit segment dihedral.

        The dihedral sweep campaign scales SECTION z values by
        ``1 + (multiplier - 1) * eta**exponent``.  OpenVSP wing segments
        instead store a constant dihedral angle per segment, so we
        reconstruct station z, scale those stations, then recover the
        per-segment angles that best reproduce the swept cruise OML.
        """
        if len(schedule) < 2 or abs(self.dihedral_multiplier - 1.0) <= 1.0e-12:
            return [dict(item) for item in schedule]

        half_span = float(self.cfg.half_span)
        z_stations = [0.0]
        for idx in range(1, len(schedule)):
            left = schedule[idx - 1]
            right = schedule[idx]
            dy = float(right["y"]) - float(left["y"])
            local_dih = float(
                right.get(
                    "segment_dihedral_deg",
                    0.5 * (float(left["dihedral_deg"]) + float(right["dihedral_deg"])),
                )
            )
            z_stations.append(z_stations[-1] + dy * math.tan(math.radians(local_dih)))

        scaled_z: list[float] = []
        scale_factors: list[float] = []
        for item, z_val in zip(schedule, z_stations):
            eta = 0.0 if half_span <= 0.0 else min(max(abs(float(item["y"])) / half_span, 0.0), 1.0)
            factor = 1.0 + (self.dihedral_multiplier - 1.0) * (eta ** self.dihedral_exponent)
            scale_factors.append(factor)
            scaled_z.append(z_val * factor)

        scaled_schedule: list[dict[str, Any]] = []
        for idx, item in enumerate(schedule):
            entry = dict(item)
            entry["dihedral_scale_factor"] = scale_factors[idx]
            entry["z_m"] = scaled_z[idx]
            if idx > 0:
                dy = float(schedule[idx]["y"]) - float(schedule[idx - 1]["y"])
                local_dih = math.degrees(math.atan2(scaled_z[idx] - scaled_z[idx - 1], dy))
                entry["dihedral_deg"] = local_dih
                entry["segment_dihedral_deg"] = local_dih
            scaled_schedule.append(entry)

        return scaled_schedule

    def _config_wing_section_schedule(self) -> List[Dict[str, Any]]:
        """Return a config-derived wing station schedule."""
        w = self.cfg.wing
        half_span = self.cfg.half_span
        segments = self.cfg.spar_segment_lengths(self.cfg.main_spar)

        # Build cumulative y stations from segment layout.
        y_stations = [0.0]
        cumsum = 0.0
        for seg_len in segments:
            cumsum += float(seg_len)
            y_stations.append(min(cumsum, half_span))
        # Ensure the tip is included.
        if abs(y_stations[-1] - half_span) > 1.0e-9:
            y_stations.append(half_span)
        # Deduplicate.
        unique_y: List[float] = []
        for y_val in y_stations:
            if not unique_y or abs(y_val - unique_y[-1]) > 1.0e-9:
                unique_y.append(y_val)

        if w.dihedral_schedule:
            return self._config_wing_schedule_from_dihedral_schedule(unique_y)

        schedule: List[Dict[str, Any]] = []
        for y_val in unique_y:
            eta = 0.0 if half_span <= 0.0 else min(max(y_val / half_span, 0.0), 1.0)
            chord = w.root_chord + eta * (w.tip_chord - w.root_chord)
            dihedral_deg = _progressive_dihedral_deg(
                eta,
                w.dihedral_root_deg,
                w.dihedral_tip_deg,
                w.dihedral_scaling_exponent,
            )
            schedule.append({
                "y": y_val,
                "chord": chord,
                "dihedral_deg": dihedral_deg,
                "airfoil": _airfoil_for_eta(self.cfg, eta),
                "source": "config",
            })

        return schedule

    def _config_wing_schedule_from_dihedral_schedule(
        self,
        y_stations: List[float],
    ) -> List[Dict[str, Any]]:
        """Build a config-derived schedule from an explicit ``z(y)`` curve."""
        w = self.cfg.wing
        half_span = self.cfg.half_span
        points = [(float(y), float(z)) for y, z in (w.dihedral_schedule or [])]
        z_stations = [self._interp_piecewise_linear(points, y_val) for y_val in y_stations]

        schedule: List[Dict[str, Any]] = []
        for idx, (y_val, z_val) in enumerate(zip(y_stations, z_stations)):
            eta = 0.0 if half_span <= 0.0 else min(max(y_val / half_span, 0.0), 1.0)
            chord = w.root_chord + eta * (w.tip_chord - w.root_chord)
            entry: Dict[str, Any] = {
                "y": y_val,
                "chord": chord,
                "dihedral_deg": 0.0,
                "airfoil": _airfoil_for_eta(self.cfg, eta),
                "source": "config_dihedral_schedule",
                "z_m": z_val,
            }
            if idx > 0:
                dy = y_val - y_stations[idx - 1]
                seg_dihedral = 0.0 if dy <= 1.0e-12 else math.degrees(
                    math.atan2(z_val - z_stations[idx - 1], dy)
                )
                entry["dihedral_deg"] = seg_dihedral
                entry["segment_dihedral_deg"] = seg_dihedral
            schedule.append(entry)

        if len(schedule) > 1:
            root_seg_dihedral = float(schedule[1].get("segment_dihedral_deg", 0.0))
            schedule[0]["dihedral_deg"] = root_seg_dihedral
            schedule[0]["segment_dihedral_deg"] = root_seg_dihedral

        return schedule

    @staticmethod
    def _interp_piecewise_linear(points: List[tuple[float, float]], y_target: float) -> float:
        """Linearly interpolate z(y) from a monotone list of schedule points."""
        if not points:
            return 0.0
        if y_target <= points[0][0] + 1.0e-9:
            return float(points[0][1])

        for idx in range(1, len(points)):
            y_left, z_left = points[idx - 1]
            y_right, z_right = points[idx]
            if y_target <= y_right + 1.0e-9:
                span = max(y_right - y_left, 1.0e-12)
                frac = min(max((y_target - y_left) / span, 0.0), 1.0)
                return float(z_left) + frac * (float(z_right) - float(z_left))

        return float(points[-1][1])

    def _reference_vsp_wing_section_schedule(self, vsp: Any | None) -> List[Dict[str, Any]] | None:
        """Extract and densify the main-wing schedule from an existing VSP model."""
        if vsp is None:
            return None
        vsp_model = self.cfg.io.vsp_model
        if vsp_model is None or not Path(vsp_model).is_file():
            return None

        try:
            vsp.ClearVSPModel()
            vsp.ReadVSPFile(str(vsp_model))
            vsp.Update()
            wing_id = self._find_reference_wing_geom(vsp)
            if wing_id is None:
                return None
            schedule = self._extract_reference_wing_schedule(vsp, wing_id)
            if len(schedule) < 2:
                return None
            densified = self._densify_reference_schedule(schedule)
            logger.info(
                "Using reference VSP main-wing section schedule from %s (%d stations)",
                vsp_model,
                len(densified),
            )
            return densified
        except Exception:
            logger.exception("Failed to extract reference VSP wing schedule; using config geometry")
            return None
        finally:
            try:
                vsp.ClearVSPModel()
            except Exception:
                pass

    @staticmethod
    def _find_reference_wing_geom(vsp: Any) -> str | None:
        geoms = list(vsp.FindGeoms())
        if not geoms:
            return None

        def norm(name: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", name.lower())

        preferred = {"mainwing", "main"}
        fallback: str | None = None
        for geom_id in geoms:
            name = norm(vsp.GetGeomName(geom_id))
            if name in preferred:
                return geom_id
            if fallback is None and "wing" in name and "elevator" not in name and "fin" not in name:
                fallback = geom_id
        return fallback

    def _extract_reference_wing_schedule(self, vsp: Any, wing_id: str) -> List[Dict[str, Any]]:
        xsec_surf = vsp.GetXSecSurf(wing_id, 0)
        n_xsecs = int(vsp.GetNumXSec(xsec_surf))
        if n_xsecs < 2:
            return []

        half_span = self.cfg.half_span
        schedule: List[Dict[str, Any]] = []
        y_accum = 0.0

        for xsec_idx in range(1, n_xsecs):
            xs = vsp.GetXSec(xsec_surf, xsec_idx)
            root_chord = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Root_Chord")))
            tip_chord = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Tip_Chord")))
            span = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Span")))
            segment_dihedral = float(vsp.GetParmVal(vsp.GetXSecParm(xs, "Dihedral")))
            if span <= 1.0e-9:
                continue

            if not schedule:
                schedule.append(
                    self._reference_schedule_entry(
                        y=0.0,
                        chord=root_chord,
                        dihedral_deg=segment_dihedral,
                        airfoil=self.cfg.wing.airfoil_root,
                    )
                )
            y_accum += span
            eta = 0.0 if half_span <= 0.0 else min(max(y_accum / half_span, 0.0), 1.0)
            schedule.append(
                self._reference_schedule_entry(
                    y=y_accum,
                    chord=tip_chord,
                    dihedral_deg=segment_dihedral,
                    segment_dihedral_deg=segment_dihedral,
                    airfoil=_airfoil_for_eta(self.cfg, eta),
                )
            )

        if schedule and abs(schedule[-1]["y"] - half_span) > 1.0e-3:
            logger.warning(
                "Reference VSP half span %.6f m differs from config half span %.6f m",
                schedule[-1]["y"],
                half_span,
            )
        airfoil_dir = Path(self.cfg.io.airfoil_dir) if self.cfg.io.airfoil_dir is not None else None
        refs = _extract_airfoil_refs(vsp, wing_id, schedule, airfoil_dir=airfoil_dir)
        for entry, ref in zip(schedule, refs, strict=False):
            name = ref.get("name")
            if name:
                entry["airfoil"] = str(name)
        return schedule

    def _densify_reference_schedule(self, schedule: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        half_span = self.cfg.half_span
        y_targets = {0.0, half_span}

        for item in schedule:
            y_targets.add(float(item["y"]))

        cumsum = 0.0
        for seg_len in self.cfg.spar_segment_lengths(self.cfg.main_spar):
            cumsum += float(seg_len)
            if -1.0e-9 <= cumsum <= half_span + 1.0e-9:
                y_targets.add(min(max(cumsum, 0.0), half_span))

        return [
            self._interpolate_reference_schedule(schedule, y)
            for y in sorted(y_targets)
            if -1.0e-9 <= y <= half_span + 1.0e-9
        ]

    def _interpolate_reference_schedule(
        self,
        schedule: List[Dict[str, Any]],
        y_target: float,
    ) -> Dict[str, Any]:
        half_span = self.cfg.half_span
        if y_target <= float(schedule[0]["y"]) + 1.0e-9:
            entry = dict(schedule[0])
            entry["y"] = 0.0
            entry["source"] = "reference_vsp"
            return entry

        for idx in range(1, len(schedule)):
            left = schedule[idx - 1]
            right = schedule[idx]
            y_left = float(left["y"])
            y_right = float(right["y"])
            if y_target <= y_right + 1.0e-9:
                if abs(y_target - y_right) <= 1.0e-9:
                    entry = dict(right)
                    entry["source"] = "reference_vsp"
                    return entry
                denom = max(y_right - y_left, 1.0e-12)
                frac = min(max((y_target - y_left) / denom, 0.0), 1.0)
                return self._reference_schedule_entry(
                    y=y_target,
                    chord=float(left["chord"]) + frac * (float(right["chord"]) - float(left["chord"])),
                    dihedral_deg=float(right["dihedral_deg"]),
                    segment_dihedral_deg=float(right.get("segment_dihedral_deg", right["dihedral_deg"])),
                    airfoil=str(left.get("airfoil") or right.get("airfoil") or self.cfg.wing.airfoil_root),
                )

        entry = dict(schedule[-1])
        entry["y"] = half_span
        entry["source"] = "reference_vsp"
        return entry

    @staticmethod
    def _reference_schedule_entry(
        *,
        y: float,
        chord: float,
        dihedral_deg: float,
        segment_dihedral_deg: float | None = None,
        airfoil: str | None = None,
    ) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "y": float(y),
            "chord": float(chord),
            "dihedral_deg": float(dihedral_deg),
            "airfoil": airfoil,
            "source": "reference_vsp",
        }
        if segment_dihedral_deg is not None:
            entry["segment_dihedral_deg"] = float(segment_dihedral_deg)
        return entry

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _resolve_airfoil_dat(self, name: str) -> Optional[Path]:
        """Locate an airfoil ``.dat`` file in the configured airfoil_dir.

        Tries several common naming conventions:
            <name>.dat, <name>.DAT, <NAME>.dat, <name>_coords.dat
        """
        af_dir = self.cfg.io.airfoil_dir
        if af_dir is None:
            return None
        af_dir = Path(af_dir)
        if not af_dir.is_dir():
            return None

        candidates = [
            af_dir / f"{name}.dat",
            af_dir / f"{name}.DAT",
            af_dir / f"{name.upper()}.dat",
            af_dir / f"{name.lower()}.dat",
            af_dir / f"{name}_coords.dat",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    @staticmethod
    def _vspscript_airfoil_block(
        xsec_idx: int,
        dat_path: Optional[Path],
        label: str,
        xsec_surf_var: str = "xsec_surf",
        var_prefix: str = "",
    ) -> str:
        """Return a VSPScript snippet that sets the airfoil for one XSec."""
        xsec_var = f"{var_prefix}xs_{xsec_idx}"
        if dat_path is not None:
            safe_path = str(dat_path).replace("\\", "/")
            return textwrap.dedent(f"""\
                // Airfoil: {label}
                ChangeXSecShape( {xsec_surf_var}, {xsec_idx}, XS_FILE_AIRFOIL );
                string {xsec_var} = GetXSec( {xsec_surf_var}, {xsec_idx} );
                ReadFileAirfoil( {xsec_var}, "{safe_path}" );
            """)
        else:
            camber, camber_loc, thick_chord = VSPBuilder._naca_4_series_params(label)
            return textwrap.dedent(f"""\
                // Airfoil: {label} (file not found — NACA 4-series fallback)
                ChangeXSecShape( {xsec_surf_var}, {xsec_idx}, XS_FOUR_SERIES );
                string {xsec_var} = GetXSec( {xsec_surf_var}, {xsec_idx} );
                SetParmVal( GetXSecParm( {xsec_var}, "Camber" ), {camber:.6f} );
                SetParmVal( GetXSecParm( {xsec_var}, "CamberLoc" ), {camber_loc:.6f} );
                SetParmVal( GetXSecParm( {xsec_var}, "ThickChord" ), {thick_chord:.6f} );
            """)

    @staticmethod
    def _naca_4_series_params(name: str) -> tuple[float, float, float]:
        """Return OpenVSP four-series camber/location/thickness parameters."""
        match = re.search(r"NACA\s*([0-9]{4})", str(name).upper())
        if match is None:
            return 0.04, 0.4, 0.12
        digits = match.group(1)
        camber = int(digits[0]) / 100.0
        camber_loc = int(digits[1]) / 10.0
        thick_chord = int(digits[2:]) / 100.0
        return camber, camber_loc, thick_chord

    @staticmethod
    def _find_output(directory: Path, stem: str, suffix: str) -> Optional[Path]:
        """Search *directory* for a file matching ``*<stem>*<suffix>``."""
        if not directory.is_dir():
            return None
        # Exact match first.
        exact = directory / f"{stem}{suffix}"
        if exact.is_file():
            return exact
        # Glob for variants (e.g. ``stem_DegenGeom.lod``).
        candidates = sorted(directory.glob(f"*{stem}*{suffix}"))
        if candidates:
            return candidates[-1]  # newest by name
        # Broaden: any file with the right suffix.
        any_match = sorted(directory.glob(f"*{suffix}"))
        if any_match:
            return any_match[-1]
        return None
