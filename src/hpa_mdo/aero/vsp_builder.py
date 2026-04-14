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

import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

from hpa_mdo.core.config import HPAConfig, LiftingSurfaceConfig
from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)

# Sentinel logged on ANY failure so the optimiser does not hang.
_FAILURE_WEIGHT = 99999

# Default timeout for VSPAero subprocess (seconds).
_VSPAERO_TIMEOUT = 600


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

    def __init__(self, cfg: HPAConfig, vspaero_timeout: int = _VSPAERO_TIMEOUT):
        self.cfg = cfg
        self.vspaero_timeout = vspaero_timeout

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
        schedule = self._wing_section_schedule()

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

                # Local dihedral: average dihedral angle for this segment.
                # OpenVSP applies the segment dihedral as a constant
                # angle across the segment span.
                local_dih = 0.5 * (inboard["dihedral_deg"] + outboard["dihedral_deg"])
                vsp.SetParmVal(vsp.GetXSecParm(xs, "Dihedral"), local_dih)
                vsp.Update()

                # Assign airfoil on the outboard XSec.
                self._assign_airfoil_api(vsp, xsec_surf, outboard_xsec_idx, outboard["airfoil"])

            logger.info(
                "MainWing: %d segments, progressive dihedral %.1f°→%.1f° (exp=%.1f)",
                n_segments, w.dihedral_root_deg, w.dihedral_tip_deg,
                w.dihedral_scaling_exponent,
            )

            # ── Symmetry (full wing from half definition) ────────────
            vsp.SetParmVal(
                vsp.FindParm(wing_id, "Sym_Planar_Flag", "Sym"),
                vsp.SYM_XZ,
            )

            self._add_lifting_surface_api(vsp, self.cfg.horizontal_tail)
            self._add_lifting_surface_api(vsp, self.cfg.vertical_fin)

            vsp.Update()

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
            vsp.SetAnalysisInputDefaults("VSPAEROComputeGeometry")
            vsp.ExecAnalysis("VSPAEROComputeGeometry")

            # ── Configure solver ─────────────────────────────────────
            analysis_name = "VSPAEROSweep"
            vsp.SetAnalysisInputDefaults(analysis_name)

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

            # VLM solver type (0 = VLM, 1 = Panel).
            vsp.SetIntAnalysisInput(analysis_name, "AnalysisMethod", [0])

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
        vspaero_bin = shutil.which("vspaero")
        if vspaero_bin is None:
            return _failure_dict("vspaero binary not found on PATH and openvsp module unavailable")

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
            local_dih = 0.5 * (inboard["dihedral_deg"] + outboard["dihedral_deg"])

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

    def _wing_section_schedule(self) -> List[Dict[str, Any]]:
        """Return the list of wing section stations for VSP multi-segment construction.

        Each entry is a dict with keys:
            y            — spanwise station [m]
            chord        — local chord [m]
            dihedral_deg — local dihedral angle [deg]
            airfoil      — airfoil name (interpolated between root and tip)

        Stations are placed at each spar segment boundary
        (from ``cfg.main_spar.segments``), which aligns the VSP
        geometry with the structural FEM model.
        """
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
            # Interpolate airfoil: use root for eta < 0.5, tip for eta >= 0.5.
            airfoil = w.airfoil_root if eta < 0.5 else w.airfoil_tip
            schedule.append({
                "y": y_val,
                "chord": chord,
                "dihedral_deg": dihedral_deg,
                "airfoil": airfoil,
            })

        return schedule

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
