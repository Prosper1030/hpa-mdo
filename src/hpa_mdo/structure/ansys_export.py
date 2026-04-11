"""Export optimised structural models to ANSYS-compatible formats.

Supported formats:
    1. ANSYS APDL macro (.mac)
    2. Workbench External Data CSV
    3. NASTRAN bulk data (.bdf)

Supported export modes:
    - ``dual_spar``: the original higher-fidelity inspection model with two
      beam lines and rigid rib links.
    - ``dual_beam_production``: the new physics-first production analysis
      export with explicit main/rear beam-line self-weight and offset-rigid
      joint links.
    - ``equivalent_beam``: a validation model that mirrors the internal FEM
      equivalent-beam assumptions used by the optimizer.

The dual-spar inspection model includes:
    - Two beam lines (main spar at 0.25c, rear spar at 0.70c)
    - BEAM188 elements with CTUBE cross-sections per element
    - Rigid links (MPC184 / CE constraints) at rib/joint positions
    - Two materials (MAT,1 for main spar, MAT,2 for rear spar)
    - Fixed root BC on both spars
    - Lift wire vertical constraint at wire attachment node
    - Applied loads: Fz (lift) on main spar, My (torque) distributed to both
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, TextIO

import numpy as np

from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.aircraft import Aircraft, WingGeometry
from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.core.materials import Material, MaterialDB
from hpa_mdo.structure.dual_beam_mainline.builder import build_dual_beam_mainline_model
from hpa_mdo.structure.dual_beam_mainline.load_split import build_dual_beam_load_split
from hpa_mdo.structure.dual_beam_mainline.types import (
    AnalysisModeName,
    LoadSplitResult,
    get_analysis_mode_definition,
)
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.structure.spar_model import (
    DualSparSection,
    compute_dual_spar_section,
    compute_outer_radius,
    segment_boundaries_from_lengths,
)

logger = logging.getLogger(__name__)


ExportMode = Literal["dual_spar", "dual_beam_production", "equivalent_beam"]
VALID_EXPORT_MODES = {"dual_spar", "dual_beam_production", "equivalent_beam"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _segment_values_to_nodes(
    seg_values: np.ndarray,
    seg_lengths: list,
    y_nodes: np.ndarray,
    *,
    scale: float,
) -> np.ndarray:
    """Map segment-level values to each structural node.

    Parameters
    ----------
    seg_values
        Segment values (for example mm-level thickness/radius arrays).
    seg_lengths
        Segment lengths [m].
    y_nodes
        Structural node locations [m].
    scale
        Unit conversion factor applied to ``seg_values``.
    """
    boundaries = segment_boundaries_from_lengths(seg_lengths)
    seg_values = np.asarray(seg_values, dtype=float).ravel()
    if seg_values.size != len(seg_lengths):
        raise ValueError(
            f"Expected {len(seg_lengths)} segment values, got {seg_values.size}."
        )
    values_si = seg_values * scale
    out = np.empty(len(y_nodes), dtype=float)
    for i, yy in enumerate(y_nodes):
        idx = int(np.searchsorted(boundaries[1:], yy, side="right"))
        idx = min(idx, len(values_si) - 1)
        out[i] = values_si[idx]
    return out


def _seg_thickness_to_nodes(
    t_seg_mm: np.ndarray,
    seg_lengths: list,
    y_nodes: np.ndarray,
) -> np.ndarray:
    """Convert segment wall thicknesses (mm) to per-node values (m)."""
    return _segment_values_to_nodes(t_seg_mm, seg_lengths, y_nodes, scale=1e-3)


def _seg_radius_to_nodes(
    r_seg_mm: np.ndarray,
    seg_lengths: list,
    y_nodes: np.ndarray,
) -> np.ndarray:
    """Convert segment outer radii (mm) to per-node values (m)."""
    return _segment_values_to_nodes(r_seg_mm, seg_lengths, y_nodes, scale=1e-3)


def _dihedral_z(y: np.ndarray, dihedral_deg: np.ndarray) -> np.ndarray:
    """Integrate dihedral angles to get Z-offset along the span."""
    z = np.zeros_like(y)
    for i in range(1, len(y)):
        dy = y[i] - y[i - 1]
        avg_dih = 0.5 * (dihedral_deg[i - 1] + dihedral_deg[i])
        z[i] = z[i - 1] + dy * np.tan(np.radians(avg_dih))
    return z


def _find_nearest_node(y_nodes: np.ndarray, y_target: float) -> int:
    """Return the 0-based index of the node closest to *y_target*."""
    return int(np.argmin(np.abs(y_nodes - y_target)))


def _node_spacings(y_nodes: np.ndarray) -> np.ndarray:
    """Return tributary length per node, matching ExternalLoadsComp."""
    dy = np.diff(y_nodes)
    out = np.zeros(len(y_nodes), dtype=float)
    out[0] = dy[0] / 2.0
    out[-1] = dy[-1] / 2.0
    for i in range(1, len(y_nodes) - 1):
        out[i] = (dy[i - 1] + dy[i]) / 2.0
    return out


def _normalise_mode(mode: str) -> str:
    """Normalise and validate an ANSYS export mode name."""
    normalised = mode.lower().replace("-", "_")
    if normalised not in VALID_EXPORT_MODES:
        choices = ", ".join(sorted(VALID_EXPORT_MODES))
        raise ValueError(f"Unknown ANSYS export mode '{mode}'. Expected one of: {choices}.")
    return normalised


# ---------------------------------------------------------------------------
# ANSYSExporter
# ---------------------------------------------------------------------------

class ANSYSExporter:
    """Generate ANSYS / NASTRAN input files for the v2 HPA wing structure."""

    def __init__(
        self,
        cfg: HPAConfig,
        aircraft: Aircraft,
        opt_result: OptimizationResult,
        aero_loads: dict,
        materials_db: MaterialDB,
        *,
        mode: ExportMode = "dual_spar",
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.opt_result = opt_result
        self.aero_loads = aero_loads
        self.materials_db = materials_db
        self.mode = _normalise_mode(mode)
        self.load_case = cfg.structural_load_cases()[0]

        wing: WingGeometry = aircraft.wing
        self.y = wing.y
        self.chord = wing.chord
        self.nn = wing.n_stations  # number of nodes per spar
        self.n_elem = self.nn - 1
        self.element_lengths = np.diff(self.y)
        self.element_centres = (self.y[:-1] + self.y[1:]) / 2.0
        self.node_spacings = _node_spacings(self.y)

        # Materials
        self.mat_main: Material = materials_db.get(cfg.main_spar.material)
        self.mat_rear: Material = materials_db.get(cfg.rear_spar.material)

        # Segment thicknesses → per-node wall thickness [m]
        main_seg_L = cfg.spar_segment_lengths(cfg.main_spar)
        rear_seg_L = cfg.spar_segment_lengths(cfg.rear_spar)
        self.main_seg_lengths = main_seg_L
        self.rear_seg_lengths = rear_seg_L

        self.t_main = _seg_thickness_to_nodes(
            opt_result.main_t_seg_mm, main_seg_L, self.y)
        self.t_main_elem = _seg_thickness_to_nodes(
            opt_result.main_t_seg_mm, main_seg_L, self.element_centres)

        if opt_result.rear_t_seg_mm is not None:
            self.t_rear = _seg_thickness_to_nodes(
                opt_result.rear_t_seg_mm, rear_seg_L, self.y)
            self.t_rear_elem = _seg_thickness_to_nodes(
                opt_result.rear_t_seg_mm, rear_seg_L, self.element_centres)
        else:
            self.t_rear = np.full(self.nn, cfg.rear_spar.min_wall_thickness)
            self.t_rear_elem = np.full(self.n_elem, cfg.rear_spar.min_wall_thickness)

        # Outer radii: prefer optimized radii from solution; fall back to
        # geometry-based reconstruction only when radii are unavailable.
        R_main_default = compute_outer_radius(
            self.y, wing.chord, wing.airfoil_thickness, cfg.main_spar
        )
        R_rear_default = compute_outer_radius(
            self.y, wing.chord, wing.airfoil_thickness, cfg.rear_spar
        )
        if opt_result.main_r_seg_mm is not None:
            self.R_main = _seg_radius_to_nodes(
                opt_result.main_r_seg_mm, main_seg_L, self.y
            )
            self.R_main_elem = _seg_radius_to_nodes(
                opt_result.main_r_seg_mm, main_seg_L, self.element_centres
            )
        else:
            self.R_main = R_main_default
            self.R_main_elem = 0.5 * (R_main_default[:-1] + R_main_default[1:])

        if opt_result.rear_r_seg_mm is not None:
            self.R_rear = _seg_radius_to_nodes(
                opt_result.rear_r_seg_mm, rear_seg_L, self.y
            )
            self.R_rear_elem = _seg_radius_to_nodes(
                opt_result.rear_r_seg_mm, rear_seg_L, self.element_centres
            )
        else:
            self.R_rear = R_rear_default
            self.R_rear_elem = 0.5 * (R_rear_default[:-1] + R_rear_default[1:])

        # Dihedral Z
        self.z_dih = _dihedral_z(self.y, wing.dihedral_deg)

        # Spar X and Z coordinates (physical, in metres)
        self.x_main = wing.main_spar_xc * wing.chord
        self.z_main = self.z_dih + wing.main_spar_z_camber
        self.x_rear = wing.rear_spar_xc * wing.chord
        self.z_rear = self.z_dih + wing.rear_spar_z_camber

        # The internal FEM is the MDO engine: one beam line at the main spar
        # chordwise station, with dihedral only in nodal Z and dual-spar
        # stiffness collapsed into equivalent section properties.
        self.x_equiv = wing.main_spar_xc * wing.chord
        self.z_equiv = self.z_dih

        # Joint / rib positions (y-coordinates)
        main_joints = HPAConfig.joint_positions(main_seg_L)
        rear_joints = HPAConfig.joint_positions(rear_seg_L)
        all_joints = sorted(set(main_joints + rear_joints))
        self.joint_y = np.array(all_joints) if all_joints else np.array([])
        self.joint_node_indices = [
            _find_nearest_node(self.y, jy) for jy in self.joint_y
        ]

        # Lift wire attachment nodes
        self.wire_nodes: list[int] = []
        if cfg.lift_wires.enabled and cfg.lift_wires.attachments:
            for att in cfg.lift_wires.attachments:
                self.wire_nodes.append(_find_nearest_node(self.y, att.y))

        # Aero loads
        self.fz_lift = np.asarray(aero_loads.get("lift_per_span", np.zeros(self.nn)))
        self.my_torque = np.asarray(aero_loads.get("torque_per_span", np.zeros(self.nn)))

        self.z_main_elem = 0.5 * (wing.main_spar_z_camber[:-1] + wing.main_spar_z_camber[1:])
        self.z_rear_elem = 0.5 * (wing.rear_spar_z_camber[:-1] + wing.rear_spar_z_camber[1:])
        chord_elem = 0.5 * (wing.chord[:-1] + wing.chord[1:])
        self.d_chord_elem = (wing.rear_spar_xc - wing.main_spar_xc) * chord_elem

        self.equivalent_section = self._compute_equivalent_section()
        self.equivalent_E = self.equivalent_section.EI_flap / (
            self.equivalent_section.Iy_equiv + 1e-30
        )
        self.equivalent_G = self.equivalent_section.GJ / (
            self.equivalent_section.J_equiv + 1e-30
        )
        self.equivalent_density = self.equivalent_section.mass_per_length / (
            self.equivalent_section.A_equiv + 1e-30
        )
        self.equivalent_rear_mass_per_length = (
            self.mat_rear.density * self.equivalent_section.A_rear
        )
        self.equivalent_fz_nodal, self.equivalent_my_nodal = self._equivalent_nodal_loads()
        self.equivalent_total_fz_n = float(np.sum(self.equivalent_fz_nodal))
        self.equivalent_total_my_nm = float(np.sum(self.equivalent_my_nodal))
        self.dual_beam_export_load_split: LoadSplitResult | None = None
        if self.mode in {"dual_spar", "dual_beam_production"}:
            analysis_mode = (
                AnalysisModeName.DUAL_SPAR_ANSYS_PARITY
                if self.mode == "dual_spar"
                else AnalysisModeName.DUAL_BEAM_PRODUCTION
            )
            self.dual_beam_export_load_split = build_dual_beam_load_split(
                model=build_dual_beam_mainline_model(
                    cfg=cfg,
                    aircraft=aircraft,
                    opt_result=opt_result,
                    export_loads=aero_loads,
                    materials_db=materials_db,
                ),
                mode_definition=get_analysis_mode_definition(analysis_mode),
            )

    def _compute_equivalent_section(self) -> DualSparSection:
        """Compute the exact equivalent section arrays used by internal FEM."""
        return compute_dual_spar_section(
            self.R_main_elem,
            self.t_main_elem,
            self.R_rear_elem,
            self.t_rear_elem,
            self.z_main_elem,
            self.z_rear_elem,
            self.d_chord_elem,
            self.mat_main.E,
            self.mat_main.G,
            self.mat_main.density,
            self.mat_rear.E,
            self.mat_rear.G,
            self.mat_rear.density,
            warping_knockdown=self.cfg.safety.dual_spar_warping_knockdown,
        )

    def _equivalent_nodal_loads(self) -> tuple[np.ndarray, np.ndarray]:
        """Return nodal Fz/My loads that match ExternalLoadsComp assumptions."""
        fz = self.fz_lift * self.node_spacings
        my = self.my_torque * self.node_spacings
        g_scaled = G_STANDARD * self.load_case.gravity_scale
        section = self.equivalent_section

        for e, length in enumerate(self.element_lengths):
            element_weight = section.mass_per_length[e] * g_scaled * length
            fz[e] -= element_weight / 2.0
            fz[e + 1] -= element_weight / 2.0

            # Rear spar self-weight acts aft of the equivalent beam axis and
            # is represented internally as a spanwise torsional moment.
            rear_weight_torque = (
                self.equivalent_rear_mass_per_length[e] * g_scaled * self.d_chord_elem[e] * length
            )
            my[e] -= rear_weight_torque / 2.0
            my[e + 1] -= rear_weight_torque / 2.0

        return fz, my

    def _dual_beam_main_nodal_fz(self) -> np.ndarray:
        if self.dual_beam_export_load_split is None:
            raise RuntimeError("Dual-beam nodal loads requested for a non dual-beam export mode.")
        return np.asarray(self.dual_beam_export_load_split.main_loads_n[:, 2], dtype=float)

    def _dual_beam_rear_nodal_fz(self) -> np.ndarray:
        if self.dual_beam_export_load_split is None:
            raise RuntimeError("Dual-beam nodal loads requested for a non dual-beam export mode.")
        return np.asarray(self.dual_beam_export_load_split.rear_loads_n[:, 2], dtype=float)

    # ==================================================================
    # APDL macro (.mac)
    # ==================================================================

    def write_apdl(self, path: str | Path) -> Path:
        """Write an ANSYS APDL macro file for the selected export mode."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w") as f:
                if self.mode == "equivalent_beam":
                    self._apdl_equivalent_write(f)
                else:
                    self._apdl_header(f)
                    self._apdl_materials(f)
                    self._apdl_element_types(f)
                    self._apdl_keypoints_and_lines(f)
                    self._apdl_sections(f)
                    self._apdl_mesh(f)
                    self._apdl_rigid_links(f)
                    self._apdl_bc(f)
                    self._apdl_loads(f)
                    self._apdl_solve(f)
            logger.info("APDL macro written to %s", path)
        except Exception:
            logger.exception("Failed to write APDL macro to %s", path)
            raise
        return path

    # -- APDL helpers ---------------------------------------------------

    def _apdl_header(self, f: TextIO) -> None:
        title = (
            "Dual-beam production ANSYS APDL input"
            if self.mode == "dual_beam_production"
            else "Dual-spar ANSYS APDL input"
        )
        f.write("! ============================================================\n")
        f.write(f"! HPA-MDO v2: {title} (auto-generated)\n")
        f.write(f"! Project     : {self.cfg.project_name}\n")
        f.write(f"! Export mode : {self.mode}\n")
        f.write(f"! Main spar   : {self.mat_main.name} at {self.cfg.main_spar.location_xc:.0%}c\n")
        f.write(f"! Rear spar   : {self.mat_rear.name} at {self.cfg.rear_spar.location_xc:.0%}c\n")
        f.write(f"! Nodes/spar  : {self.nn}\n")
        f.write(f"! Rib links   : {len(self.joint_node_indices)}\n")
        f.write(f"! Wire attach : {len(self.wire_nodes)} node(s)\n")
        f.write("! ============================================================\n\n")
        f.write("/PREP7\n\n")

    def _apdl_materials(self, f: TextIO) -> None:
        f.write("! --- Material 1: Main spar ---\n")
        f.write(f"MP,EX,1,{self.mat_main.E:.6e}       ! Young's modulus [Pa]\n")
        f.write(f"MP,GXY,1,{self.mat_main.G:.6e}      ! Shear modulus [Pa]\n")
        f.write(f"MP,DENS,1,{self.mat_main.density:.1f}          ! Density [kg/m3]\n")
        f.write(f"MP,PRXY,1,{self.mat_main.poisson_ratio:.3f}       ! Poisson ratio\n\n")

        f.write("! --- Material 2: Rear spar ---\n")
        f.write(f"MP,EX,2,{self.mat_rear.E:.6e}\n")
        f.write(f"MP,GXY,2,{self.mat_rear.G:.6e}\n")
        f.write(f"MP,DENS,2,{self.mat_rear.density:.1f}\n")
        f.write(f"MP,PRXY,2,{self.mat_rear.poisson_ratio:.3f}\n\n")

    def _apdl_element_types(self, f: TextIO) -> None:
        f.write("! --- Element types ---\n")
        f.write("! TYPE 1: BEAM188 for main spar\n")
        f.write("ET,1,BEAM188\n")
        f.write("KEYOPT,1,1,0    ! No warping DOF\n")
        f.write("KEYOPT,1,3,2    ! Cubic shape functions\n\n")

        f.write("! TYPE 2: BEAM188 for rear spar\n")
        f.write("ET,2,BEAM188\n")
        f.write("KEYOPT,2,1,0\n")
        f.write("KEYOPT,2,3,2\n\n")

        f.write("! TYPE 3: MPC184 rigid link (rib connection)\n")
        f.write("ET,3,MPC184\n")
        f.write("KEYOPT,3,1,1    ! Rigid beam\n\n")

    def _apdl_keypoints_and_lines(self, f: TextIO) -> None:
        nn = self.nn

        # Main spar keypoints: 1..nn
        f.write("! --- Main spar keypoints (1 .. %d) ---\n" % nn)
        for j in range(nn):
            f.write(f"K,{j + 1}, {self.x_main[j]:.6f}, {self.y[j]:.6f}, {self.z_main[j]:.6f}\n")
        f.write("\n")

        # Rear spar keypoints: nn+1..2*nn
        f.write("! --- Rear spar keypoints (%d .. %d) ---\n" % (nn + 1, 2 * nn))
        for j in range(nn):
            kid = nn + j + 1
            f.write(f"K,{kid}, {self.x_rear[j]:.6f}, {self.y[j]:.6f}, {self.z_rear[j]:.6f}\n")
        f.write("\n")

        # Main spar lines
        f.write("! --- Main spar lines ---\n")
        for j in range(nn - 1):
            f.write(f"L,{j + 1},{j + 2}\n")
        f.write("\n")

        # Rear spar lines
        f.write("! --- Rear spar lines ---\n")
        for j in range(nn - 1):
            f.write(f"L,{nn + j + 1},{nn + j + 2}\n")
        f.write("\n")

    def _apdl_sections(self, f: TextIO) -> None:
        nn = self.nn
        n_elem = nn - 1

        # Main spar sections: SECNUM 1 .. n_elem
        f.write("! --- Main spar cross-sections (CTUBE) ---\n")
        for j in range(n_elem):
            sec_id = j + 1
            R_o = 0.5 * (self.R_main[j] + self.R_main[j + 1])
            t_w = 0.5 * (self.t_main[j] + self.t_main[j + 1])
            R_i = max(R_o - t_w, 0.0)
            f.write(f"SECTYPE,{sec_id},BEAM,CTUBE\n")
            f.write(f"SECDATA,{R_i:.6f},{R_o:.6f}\n")
        f.write("\n")

        # Rear spar sections: SECNUM n_elem+1 .. 2*n_elem
        f.write("! --- Rear spar cross-sections (CTUBE) ---\n")
        for j in range(n_elem):
            sec_id = n_elem + j + 1
            R_o = 0.5 * (self.R_rear[j] + self.R_rear[j + 1])
            t_w = 0.5 * (self.t_rear[j] + self.t_rear[j + 1])
            R_i = max(R_o - t_w, 0.0)
            f.write(f"SECTYPE,{sec_id},BEAM,CTUBE\n")
            f.write(f"SECDATA,{R_i:.6f},{R_o:.6f}\n")
        f.write("\n")

    def _apdl_mesh(self, f: TextIO) -> None:
        nn = self.nn
        n_elem = nn - 1

        # Main spar meshing (lines 1..n_elem)
        f.write("! --- Mesh main spar (MAT=1, TYPE=1) ---\n")
        for j in range(n_elem):
            line_id = j + 1
            sec_id = j + 1
            f.write(f"LSEL,S,LINE,,{line_id}\n")
            f.write(f"LATT,1,,1,,,,{sec_id}    ! MAT=1, TYPE=1, SECNUM={sec_id}\n")
            f.write("LESIZE,ALL,,,1\n")
            f.write("LMESH,ALL\n")
        f.write("ALLSEL,ALL\n\n")

        # Rear spar meshing (lines n_elem+1..2*n_elem)
        f.write("! --- Mesh rear spar (MAT=2, TYPE=2) ---\n")
        for j in range(n_elem):
            line_id = n_elem + j + 1
            sec_id = n_elem + j + 1
            f.write(f"LSEL,S,LINE,,{line_id}\n")
            f.write(f"LATT,2,,2,,,,{sec_id}    ! MAT=2, TYPE=2, SECNUM={sec_id}\n")
            f.write("LESIZE,ALL,,,1\n")
            f.write("LMESH,ALL\n")
        f.write("ALLSEL,ALL\n\n")

    def _apdl_rigid_links(self, f: TextIO) -> None:
        """Connect main↔rear nodes at rib joints with mode-specific rigid links."""
        if len(self.joint_node_indices) == 0:
            f.write("! --- No rib links (no joints) ---\n\n")
            return

        nn = self.nn
        if self.mode == "dual_beam_production":
            f.write("! --- Offset-rigid rib links (CERIG at joint positions) ---\n")
            f.write("! Main spar node N is the master; rear spar node N+%d is the slave.\n" % nn)
            for idx in self.joint_node_indices:
                main_node = idx + 1
                rear_node = nn + idx + 1
                f.write(f"CERIG,{main_node},{rear_node},ALL\n")
        else:
            f.write("! --- Rigid rib links (CE constraints at joint positions) ---\n")
            f.write("! Main spar node N  <-->  Rear spar node N+%d\n" % nn)
            f.write("! All 6 DOFs coupled with parity-style equal-DOF constraints.\n")
            for idx in self.joint_node_indices:
                main_node = idx + 1           # 1-based APDL node number
                rear_node = nn + idx + 1      # rear spar node
                for dof_label in ["UX", "UY", "UZ", "ROTX", "ROTY", "ROTZ"]:
                    f.write(f"CE,NEXT,0, {main_node},{dof_label},1, {rear_node},{dof_label},-1\n")
        f.write("\n")

    def _apdl_bc(self, f: TextIO) -> None:
        nn = self.nn

        # Fixed root on both spars
        f.write("! --- Boundary conditions: fixed root on both spars ---\n")
        f.write("DK,1,ALL,0        ! Main spar root\n")
        f.write(f"DK,{nn + 1},ALL,0  ! Rear spar root\n\n")

        # Lift wire vertical constraint
        if self.wire_nodes:
            f.write("! --- Lift wire vertical constraint ---\n")
            for wn in self.wire_nodes:
                kp_main = wn + 1
                f.write(f"DK,{kp_main},UZ,0   ! Wire attachment at y={self.y[wn]:.2f}m\n")
            f.write("\n")

    def _apdl_loads(self, f: TextIO) -> None:
        nn = self.nn
        tol = 1e-10

        if self.dual_beam_export_load_split is None:
            raise RuntimeError("Dual-beam APDL loads require an explicit dual-beam load split.")

        fz_main = self._dual_beam_main_nodal_fz()
        fz_rear = self._dual_beam_rear_nodal_fz()

        if self.mode == "dual_beam_production":
            f.write("! --- Production dual-beam nodal FZ loads from the mainline load split ---\n")
            f.write("! Main spar FZ includes lift, aerodynamic torque couple, and main tube self-weight.\n")
            f.write("! Rear spar FZ includes aerodynamic torque couple and rear tube self-weight.\n")
            f.write("! No equivalent-beam rear-gravity torque is added in this export mode.\n")
        else:
            f.write("! --- Parity dual-spar nodal FZ loads from the mainline parity split ---\n")
            f.write("! Main spar FZ includes lift and aerodynamic torque couple only.\n")
            f.write("! Rear spar FZ includes the equal/opposite aerodynamic torque couple only.\n")

        f.write("! --- Final nodal FZ loads (one FK per node DOF) ---\n")
        for j in range(nn):
            val_main = fz_main[j]
            if abs(val_main) > tol:
                f.write(f"FK,{j + 1},FZ,{val_main:.6f}    ! main y={self.y[j]:.3f}m\n")

            val_rear = fz_rear[j]
            if abs(val_rear) > tol:
                f.write(f"FK,{nn + j + 1},FZ,{val_rear:.6f}    ! rear y={self.y[j]:.3f}m\n")
        f.write("\n")

    def _apdl_solve(self, f: TextIO) -> None:
        f.write("! --- Solution ---\n")
        f.write("FINISH\n")
        f.write("/SOLU\n")
        f.write("ANTYPE,STATIC\n")
        f.write("SOLVE\n")
        f.write("FINISH\n\n")

        f.write("! --- Post-processing ---\n")
        f.write("/POST1\n")
        f.write("SET,LAST\n")
        f.write(f"*GET,TIP_UZ,NODE,{self.nn},U,Z\n")
        if self.mode == "dual_beam_production":
            f.write(f"*GET,TIP_REAR_UZ,NODE,{2 * self.nn},U,Z\n")
        f.write("\n")
        f.write("! Restrict beam result post-processing to BEAM188 types only.\n")
        f.write("ESEL,S,TYPE,,1,2\n")
        f.write("ETABLE,VM_I,SMISC,31   ! BEAM188 von Mises at i-end\n")
        f.write("ETABLE,VM_J,SMISC,36   ! BEAM188 von Mises at j-end\n")
        f.write("*GET,VM_I_MAX,ETAB,VM_I,MAX\n")
        f.write("*GET,VM_J_MAX,ETAB,VM_J,MAX\n")
        f.write("ALLSEL,ALL\n")
        f.write("PRRSOL,FZ\n")
        f.write("\n")
        f.write("/OUTPUT,ansys_post,txt\n")
        f.write(
            "*VWRITE,TIP_UZ,VM_I_MAX,VM_J_MAX\n"
        )
        f.write(
            "('TIP_UZ=',E16.8,', VM_I_MAX=',E16.8,', VM_J_MAX=',E16.8)\n"
        )
        f.write("/OUTPUT\n")
        f.write("FINISH\n")

    # -- Equivalent-beam APDL helpers ---------------------------------

    def _apdl_equivalent_write(self, f: TextIO) -> None:
        self._apdl_equivalent_header(f)
        self._apdl_equivalent_materials(f)
        self._apdl_equivalent_element_types(f)
        self._apdl_equivalent_keypoints_and_lines(f)
        self._apdl_equivalent_sections(f)
        self._apdl_equivalent_mesh(f)
        self._apdl_equivalent_bc(f)
        self._apdl_equivalent_loads(f)
        self._apdl_equivalent_solve(f)

    def _apdl_equivalent_header(self, f: TextIO) -> None:
        f.write("! ============================================================\n")
        f.write("! HPA-MDO v2: Equivalent-beam ANSYS APDL input (auto-generated)\n")
        f.write(f"! Project     : {self.cfg.project_name}\n")
        f.write("! Export mode : equivalent_beam\n")
        f.write("! Purpose     : Phase I validation against the internal FEM model\n")
        f.write(f"! Nodes/beam  : {self.nn}\n")
        f.write(f"! Wire attach : {len(self.wire_nodes)} node(s)\n")
        f.write("! Notes       : Single BEAM188 line uses the same equivalent A/I/J\n")
        f.write("!               properties and nodal load assumptions as the MDO solver.\n")
        f.write("!               The dual_spar mode remains available for inspection only.\n")
        f.write("! ============================================================\n\n")
        f.write("/PREP7\n\n")

    def _apdl_equivalent_materials(self, f: TextIO) -> None:
        f.write("! --- Elementwise equivalent materials ---\n")
        f.write("! E/G/density are back-computed from the internal equivalent section arrays.\n")
        for e in range(self.n_elem):
            mat_id = e + 1
            E = float(self.equivalent_E[e])
            G = float(self.equivalent_G[e])
            rho = float(self.equivalent_density[e])
            nu = E / (2.0 * G) - 1.0 if G > 0.0 else self.mat_main.poisson_ratio
            nu = float(np.clip(nu, 0.0, 0.499))
            f.write(f"MP,EX,{mat_id},{E:.6e}       ! Equivalent Young's modulus [Pa]\n")
            f.write(f"MP,GXY,{mat_id},{G:.6e}      ! Equivalent shear modulus [Pa]\n")
            f.write(f"MP,DENS,{mat_id},{rho:.6e}   ! Equivalent density [kg/m3]\n")
            f.write(f"MP,PRXY,{mat_id},{nu:.6f}    ! Derived from E/(2G)-1\n")
        f.write("\n")

    def _apdl_equivalent_element_types(self, f: TextIO) -> None:
        f.write("! --- Element type ---\n")
        f.write("ET,1,BEAM188\n")
        f.write("KEYOPT,1,1,0    ! No warping DOF, matching internal beam topology\n")
        f.write("KEYOPT,1,3,2    ! Cubic shape functions\n\n")

    def _apdl_equivalent_keypoints_and_lines(self, f: TextIO) -> None:
        f.write("! --- Equivalent beam keypoints (1 .. %d) ---\n" % self.nn)
        for j in range(self.nn):
            f.write(
                f"K,{j + 1}, {self.x_equiv[j]:.6f}, {self.y[j]:.6f}, {self.z_equiv[j]:.6f}\n"
            )
        f.write("\n")

        f.write("! --- Equivalent beam lines ---\n")
        for j in range(self.n_elem):
            f.write(f"L,{j + 1},{j + 2}\n")
        f.write("\n")

    def _apdl_equivalent_sections(self, f: TextIO) -> None:
        f.write("! --- Equivalent beam sections (ASEC) ---\n")
        f.write(
            "! SECDATA convention used here: A, IYY, IYZ, IZZ, IW, J, "
            "CGY, CGZ, SHY, SHZ, TKZ, TKY, TSXZ, TSXY.\n"
        )
        f.write("! These are effective properties for stiffness validation, not physical tube fibers.\n")
        section = self.equivalent_section
        for e in range(self.n_elem):
            sec_id = e + 1
            area = float(section.A_equiv[e])
            tkz = float(np.sqrt(max(12.0 * section.Iy_equiv[e] / max(area, 1e-30), 0.0)))
            tky = float(np.sqrt(max(12.0 * section.Iz_equiv[e] / max(area, 1e-30), 0.0)))
            f.write(f"SECTYPE,{sec_id},BEAM,ASEC\n")
            f.write(
                "SECDATA,"
                f"{section.A_equiv[e]:.8e},"
                f"{section.Iy_equiv[e]:.8e},"
                "0.00000000e+00,"
                f"{section.Iz_equiv[e]:.8e},"
                "0.00000000e+00,"
                f"{section.J_equiv[e]:.8e},"
                "0.00000000e+00,0.00000000e+00,"
                "0.00000000e+00,0.00000000e+00,"
                f"{tkz:.8e},{tky:.8e},"
                "5.00000000e-01,5.00000000e-01\n"
            )
        f.write("\n")

    def _apdl_equivalent_mesh(self, f: TextIO) -> None:
        f.write("! --- Mesh equivalent beam ---\n")
        for e in range(self.n_elem):
            line_id = e + 1
            mat_id = e + 1
            sec_id = e + 1
            f.write(f"LSEL,S,LINE,,{line_id}\n")
            f.write(f"LATT,{mat_id},,1,,,,{sec_id}    ! MAT={mat_id}, TYPE=1, SECNUM={sec_id}\n")
            f.write("LESIZE,ALL,,,1\n")
            f.write("LMESH,ALL\n")
        f.write("ALLSEL,ALL\n\n")

    def _apdl_equivalent_bc(self, f: TextIO) -> None:
        f.write("! --- Boundary conditions: fixed root on the internal FEM beam ---\n")
        f.write("DK,1,ALL,0\n\n")

        if self.wire_nodes:
            f.write("! --- Lift wire vertical constraint, same node mapping as internal FEM ---\n")
            for wn in self.wire_nodes:
                kp = wn + 1
                f.write(f"DK,{kp},UZ,0   ! Wire attachment at y={self.y[wn]:.2f}m\n")
            f.write("\n")

    def _apdl_equivalent_loads(self, f: TextIO) -> None:
        tol = 1e-10
        f.write("! --- Equivalent FEM nodal loads ---\n")
        f.write("! FZ includes aero lift plus spar self-weight/inertia from mass_per_length.\n")
        f.write("! MY is applied directly as the internal spanwise torsional moment DOF.\n")
        for j in range(self.nn):
            fz = self.equivalent_fz_nodal[j]
            my = self.equivalent_my_nodal[j]
            if abs(fz) > tol:
                f.write(f"FK,{j + 1},FZ,{fz:.6f}    ! y={self.y[j]:.3f}m\n")
            if abs(my) > tol:
                f.write(f"FK,{j + 1},MY,{my:.6f}    ! y={self.y[j]:.3f}m\n")
        f.write("\n")

    def _apdl_equivalent_solve(self, f: TextIO) -> None:
        f.write("! --- Solution ---\n")
        f.write("FINISH\n")
        f.write("/SOLU\n")
        f.write("ANTYPE,STATIC\n")
        f.write("SOLVE\n")
        f.write("FINISH\n\n")

        f.write("! --- Post-processing ---\n")
        f.write("/POST1\n")
        f.write("SET,LAST\n")
        f.write(f"*GET,TIP_UZ,NODE,{self.nn},U,Z\n")
        f.write("PRRSOL,FZ\n")
        f.write("\n")
        f.write("! Stress is intentionally non-gating in equivalent_beam mode.\n")
        f.write("! ASEC stresses are effective-section stresses, not the internal main/rear tube fiber checks.\n")
        f.write("/OUTPUT,ansys_post,txt\n")
        f.write("*VWRITE,TIP_UZ\n")
        f.write("('TIP_UZ=',E16.8)\n")
        f.write("/OUTPUT\n")
        f.write("FINISH\n")

    # ==================================================================
    # Workbench External Data CSV
    # ==================================================================

    def write_workbench_csv(self, path: str | Path) -> Path:
        """Write geometry + loads as CSV for ANSYS Workbench."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import csv

            if self.mode == "equivalent_beam":
                return self._write_equivalent_workbench_csv(path)

            with open(path, "w", newline="") as csvfile:
                writer = csv.writer(csvfile)
                header = [
                    "Node",
                    "Y_Position_m",
                    # Main spar
                    "Main_X_m", "Main_Z_m",
                    "Main_Outer_Radius_m", "Main_Wall_Thickness_m",
                    # Rear spar
                    "Rear_X_m", "Rear_Z_m",
                    "Rear_Outer_Radius_m", "Rear_Wall_Thickness_m",
                    # Loads
                    "Lift_Per_Span_N_m", "Torque_Per_Span_Nm_m",
                    "Main_FZ_N", "Rear_FZ_N",
                    # Flags
                    "Is_Joint", "Is_Wire_Attach",
                ]
                writer.writerow(header)

                joint_set = set(self.joint_node_indices)
                wire_set = set(self.wire_nodes)
                main_fz = (
                    self._dual_beam_main_nodal_fz()
                    if self.dual_beam_export_load_split is not None
                    else np.zeros(self.nn, dtype=float)
                )
                rear_fz = (
                    self._dual_beam_rear_nodal_fz()
                    if self.dual_beam_export_load_split is not None
                    else np.zeros(self.nn, dtype=float)
                )

                for j in range(self.nn):
                    writer.writerow([
                        j + 1,
                        f"{self.y[j]:.8e}",
                        f"{self.x_main[j]:.8e}", f"{self.z_main[j]:.8e}",
                        f"{self.R_main[j]:.8e}", f"{self.t_main[j]:.8e}",
                        f"{self.x_rear[j]:.8e}", f"{self.z_rear[j]:.8e}",
                        f"{self.R_rear[j]:.8e}", f"{self.t_rear[j]:.8e}",
                        f"{self.fz_lift[j]:.8e}", f"{self.my_torque[j]:.8e}",
                        f"{main_fz[j]:.8e}", f"{rear_fz[j]:.8e}",
                        1 if j in joint_set else 0,
                        1 if j in wire_set else 0,
                    ])

            logger.info("Workbench CSV written to %s", path)
        except Exception:
            logger.exception("Failed to write Workbench CSV to %s", path)
            raise
        return path

    def _write_equivalent_workbench_csv(self, path: Path) -> Path:
        """Write equivalent-beam geometry/properties for validation imports."""
        import csv

        section = self.equivalent_section
        with open(path, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow([
                "Node",
                "Y_Position_m",
                "Beam_X_m",
                "Beam_Z_m",
                "FZ_N",
                "MY_Nm",
                "Is_Wire_Attach",
                "Element_After",
                "A_equiv_m2",
                "Iy_equiv_m4",
                "Iz_equiv_m4",
                "J_equiv_m4",
                "E_equiv_Pa",
                "G_equiv_Pa",
                "Mass_Per_Length_kg_m",
            ])

            wire_set = set(self.wire_nodes)
            for j in range(self.nn):
                if j < self.n_elem:
                    elem = j + 1
                    elem_values = [
                        elem,
                        f"{section.A_equiv[j]:.8e}",
                        f"{section.Iy_equiv[j]:.8e}",
                        f"{section.Iz_equiv[j]:.8e}",
                        f"{section.J_equiv[j]:.8e}",
                        f"{self.equivalent_E[j]:.8e}",
                        f"{self.equivalent_G[j]:.8e}",
                        f"{section.mass_per_length[j]:.8e}",
                    ]
                else:
                    elem_values = ["", "", "", "", "", "", "", ""]

                writer.writerow([
                    j + 1,
                    f"{self.y[j]:.8e}",
                    f"{self.x_equiv[j]:.8e}",
                    f"{self.z_equiv[j]:.8e}",
                    f"{self.equivalent_fz_nodal[j]:.8e}",
                    f"{self.equivalent_my_nodal[j]:.8e}",
                    1 if j in wire_set else 0,
                    *elem_values,
                ])

        logger.info("Workbench CSV written to %s", path)
        return path

    # ==================================================================
    # NASTRAN Bulk Data (.bdf)
    # ==================================================================

    def write_nastran_bdf(self, path: str | Path) -> Path:
        """Write a NASTRAN BDF for the selected export mode."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w") as f:
                if self.mode == "equivalent_beam":
                    self._bdf_equivalent_write(f)
                else:
                    self._bdf_write(f)
            logger.info("NASTRAN BDF written to %s", path)
        except Exception:
            logger.exception("Failed to write NASTRAN BDF to %s", path)
            raise
        return path

    def _bdf_write(self, f: TextIO) -> None:
        nn = self.nn
        n_elem = nn - 1

        f.write("$ HPA-MDO v2: Dual-spar NASTRAN Bulk Data (auto-generated)\n")
        f.write("BEGIN BULK\n")

        # -- Materials (MAT1) --
        f.write("$ --- Material 1: Main spar ---\n")
        G1 = self.mat_main.G
        f.write(f"MAT1,1,{self.mat_main.E:.4e},{G1:.4e},"
                f"{self.mat_main.poisson_ratio},{self.mat_main.density}\n")

        f.write("$ --- Material 2: Rear spar ---\n")
        G2 = self.mat_rear.G
        f.write(f"MAT1,2,{self.mat_rear.E:.4e},{G2:.4e},"
                f"{self.mat_rear.poisson_ratio},{self.mat_rear.density}\n")

        # -- Grid points --
        # Main spar: GID 1..nn
        f.write("$ --- Main spar grid points ---\n")
        for j in range(nn):
            gid = j + 1
            f.write(f"GRID,{gid},,{self.x_main[j]:.6f},{self.y[j]:.6f},{self.z_main[j]:.6f}\n")

        # Rear spar: GID nn+1..2*nn
        f.write("$ --- Rear spar grid points ---\n")
        for j in range(nn):
            gid = nn + j + 1
            f.write(f"GRID,{gid},,{self.x_rear[j]:.6f},{self.y[j]:.6f},{self.z_rear[j]:.6f}\n")

        # -- Beam properties and elements --
        # Main spar: PID 1..n_elem, EID 1..n_elem
        f.write("$ --- Main spar CBAR elements ---\n")
        for j in range(n_elem):
            eid = j + 1
            pid = j + 1
            R_o = 0.5 * (self.R_main[j] + self.R_main[j + 1])
            t_w = 0.5 * (self.t_main[j] + self.t_main[j + 1])
            f.write(f"PBARL,{pid},1,,TUBE\n")
            f.write(f",{R_o:.6f},{t_w:.6f}\n")
            # Orientation vector: Z-axis (0,0,1)
            f.write(f"CBAR,{eid},{pid},{j + 1},{j + 2},0.0,0.0,1.0\n")

        # Rear spar: PID n_elem+1..2*n_elem, EID n_elem+1..2*n_elem
        f.write("$ --- Rear spar CBAR elements ---\n")
        for j in range(n_elem):
            eid = n_elem + j + 1
            pid = n_elem + j + 1
            R_o = 0.5 * (self.R_rear[j] + self.R_rear[j + 1])
            t_w = 0.5 * (self.t_rear[j] + self.t_rear[j + 1])
            f.write(f"PBARL,{pid},2,,TUBE\n")
            f.write(f",{R_o:.6f},{t_w:.6f}\n")
            ga = nn + j + 1
            gb = nn + j + 2
            f.write(f"CBAR,{eid},{pid},{ga},{gb},0.0,0.0,1.0\n")

        # -- Rigid links at joint/rib positions (MPC / RBE2) --
        if self.joint_node_indices:
            if self.mode == "dual_beam_production":
                f.write("$ --- Offset-rigid rib links (RBE2) ---\n")
            else:
                f.write("$ --- Parity-style rib links (RBE2 export surrogate) ---\n")
            rbe_id = 2 * n_elem + 1
            for idx in self.joint_node_indices:
                main_gid = idx + 1
                rear_gid = nn + idx + 1
                # RBE2 with non-coincident grids behaves as an offset-rigid link.
                f.write(f"RBE2,{rbe_id},{main_gid},123456,{rear_gid}\n")
                rbe_id += 1

        # -- Boundary conditions --
        f.write("$ --- Fixed root (both spars) ---\n")
        f.write("SPC1,1,123456,1\n")
        f.write(f"SPC1,1,123456,{nn + 1}\n")

        # Lift wire constraint
        if self.wire_nodes:
            f.write("$ --- Lift wire vertical constraint ---\n")
            for wn in self.wire_nodes:
                gid = wn + 1
                f.write(f"SPC1,1,3,{gid}   $ Wire at y={self.y[wn]:.2f}m\n")

        if self.dual_beam_export_load_split is None:
            raise RuntimeError("Dual-beam BDF export requires an explicit dual-beam load split.")

        main_fz = self._dual_beam_main_nodal_fz()
        rear_fz = self._dual_beam_rear_nodal_fz()

        # -- Applied loads --
        f.write("$ --- Dual-beam nodal FZ loads ---\n")
        for j in range(nn):
            main_val = main_fz[j]
            if abs(main_val) > 1e-10:
                direction = 1.0 if main_val > 0 else -1.0
                f.write(f"FORCE,1,{j + 1},,{abs(main_val):.6f},0.0,0.0,{direction}\n")
            rear_val = rear_fz[j]
            if abs(rear_val) > 1e-10:
                direction = 1.0 if rear_val > 0 else -1.0
                f.write(f"FORCE,1,{nn + j + 1},,{abs(rear_val):.6f},0.0,0.0,{direction}\n")

        f.write("ENDDATA\n")

    def _bdf_equivalent_write(self, f: TextIO) -> None:
        nn = self.nn
        n_elem = self.n_elem
        section = self.equivalent_section

        f.write("$ HPA-MDO v2: Equivalent-beam NASTRAN Bulk Data (auto-generated)\n")
        f.write("$ Export mode: equivalent_beam; Phase I validation model\n")
        f.write("BEGIN BULK\n")

        for e in range(n_elem):
            mid = e + 1
            E = float(self.equivalent_E[e])
            G = float(self.equivalent_G[e])
            rho = float(self.equivalent_density[e])
            nu = E / (2.0 * G) - 1.0 if G > 0.0 else self.mat_main.poisson_ratio
            nu = float(np.clip(nu, 0.0, 0.499))
            f.write(f"MAT1,{mid},{E:.4e},{G:.4e},{nu:.6f},{rho:.6e}\n")

        f.write("$ --- Equivalent beam grid points ---\n")
        for j in range(nn):
            gid = j + 1
            f.write(
                f"GRID,{gid},,{self.x_equiv[j]:.6f},{self.y[j]:.6f},{self.z_equiv[j]:.6f}\n"
            )

        f.write("$ --- Equivalent CBAR elements/properties ---\n")
        for e in range(n_elem):
            eid = e + 1
            pid = e + 1
            mid = e + 1
            f.write(
                f"PBAR,{pid},{mid},{section.A_equiv[e]:.8e},"
                f"{section.Iy_equiv[e]:.8e},{section.Iz_equiv[e]:.8e},"
                f"{section.J_equiv[e]:.8e}\n"
            )
            f.write(f"CBAR,{eid},{pid},{e + 1},{e + 2},0.0,0.0,1.0\n")

        f.write("$ --- Fixed root and lift-wire vertical support ---\n")
        f.write("SPC1,1,123456,1\n")
        for wn in self.wire_nodes:
            f.write(f"SPC1,1,3,{wn + 1}   $ Wire at y={self.y[wn]:.2f}m\n")

        f.write("$ --- Equivalent FEM nodal loads ---\n")
        for j in range(nn):
            fz = self.equivalent_fz_nodal[j]
            if abs(fz) > 1e-10:
                direction = 1.0 if fz > 0 else -1.0
                f.write(f"FORCE,1,{j + 1},,{abs(fz):.6f},0.0,0.0,{direction}\n")
            my = self.equivalent_my_nodal[j]
            if abs(my) > 1e-10:
                direction = 1.0 if my > 0 else -1.0
                f.write(f"MOMENT,1,{j + 1},,{abs(my):.6f},0.0,{direction},0.0\n")

        f.write("ENDDATA\n")
