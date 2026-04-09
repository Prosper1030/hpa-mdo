"""Export optimised dual-spar geometry and loads to ANSYS-compatible formats.

Supported formats:
    1. ANSYS APDL macro (.mac) — 3-D dual-beam model with rigid rib links
    2. Workbench External Data CSV — tabular data for both spars
    3. NASTRAN bulk data (.bdf) — CBAR beams + MPC rigid links

The exported model includes:
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
from typing import TextIO

import numpy as np

from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.aircraft import Aircraft, WingGeometry
from hpa_mdo.core.materials import Material, MaterialDB
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.structure.spar_model import (
    compute_outer_radius,
    segment_boundaries_from_lengths,
)

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# ANSYSExporter
# ---------------------------------------------------------------------------

class ANSYSExporter:
    """Generate ANSYS / NASTRAN input files for the v2 dual-spar HPA wing."""

    def __init__(
        self,
        cfg: HPAConfig,
        aircraft: Aircraft,
        opt_result: OptimizationResult,
        aero_loads: dict,
        materials_db: MaterialDB,
    ):
        self.cfg = cfg
        self.aircraft = aircraft
        self.opt_result = opt_result
        self.aero_loads = aero_loads
        self.materials_db = materials_db

        wing: WingGeometry = aircraft.wing
        self.y = wing.y
        self.chord = wing.chord
        self.nn = wing.n_stations  # number of nodes per spar

        # Materials
        self.mat_main: Material = materials_db.get(cfg.main_spar.material)
        self.mat_rear: Material = materials_db.get(cfg.rear_spar.material)

        # Segment thicknesses → per-node wall thickness [m]
        main_seg_L = cfg.spar_segment_lengths(cfg.main_spar)
        rear_seg_L = cfg.spar_segment_lengths(cfg.rear_spar)

        self.t_main = _seg_thickness_to_nodes(
            opt_result.main_t_seg_mm, main_seg_L, self.y)

        if opt_result.rear_t_seg_mm is not None:
            self.t_rear = _seg_thickness_to_nodes(
                opt_result.rear_t_seg_mm, rear_seg_L, self.y)
        else:
            self.t_rear = np.full(self.nn, cfg.rear_spar.min_wall_thickness)

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
        else:
            self.R_main = R_main_default

        if opt_result.rear_r_seg_mm is not None:
            self.R_rear = _seg_radius_to_nodes(
                opt_result.rear_r_seg_mm, rear_seg_L, self.y
            )
        else:
            self.R_rear = R_rear_default

        # Dihedral Z
        self.z_dih = _dihedral_z(self.y, wing.dihedral_deg)

        # Spar X and Z coordinates (physical, in metres)
        self.x_main = wing.main_spar_xc * wing.chord
        self.z_main = self.z_dih + wing.main_spar_z_camber * wing.chord
        self.x_rear = wing.rear_spar_xc * wing.chord
        self.z_rear = self.z_dih + wing.rear_spar_z_camber * wing.chord

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

    # ==================================================================
    # APDL macro (.mac)
    # ==================================================================

    def write_apdl(self, path: str | Path) -> Path:
        """Write a 3-D dual-beam ANSYS APDL macro file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w") as f:
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
        f.write("! ============================================================\n")
        f.write("! HPA-MDO v2: Dual-spar ANSYS APDL input (auto-generated)\n")
        f.write(f"! Project     : {self.cfg.project_name}\n")
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
        """Constraint equations (CE) connecting main↔rear nodes at rib joints."""
        if len(self.joint_node_indices) == 0:
            f.write("! --- No rib links (no joints) ---\n\n")
            return

        nn = self.nn
        f.write("! --- Rigid rib links (CE constraints at joint positions) ---\n")
        f.write("! Main spar node N  <-->  Rear spar node N+%d\n" % nn)
        f.write("! All 6 DOFs coupled (rigid rib)\n")

        for idx in self.joint_node_indices:
            main_node = idx + 1           # 1-based APDL node number
            rear_node = nn + idx + 1      # rear spar node
            # Couple all 6 DOFs via CE command
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
        dy = np.diff(self.y)

        # --- Fz lift on main spar ---
        f.write("! --- Applied lift loads (Fz) on main spar ---\n")
        for j in range(nn):
            if j == 0:
                F_node = self.fz_lift[j] * dy[0] / 2.0
            elif j == nn - 1:
                F_node = self.fz_lift[j] * dy[-1] / 2.0
            else:
                F_node = self.fz_lift[j] * (dy[j - 1] + dy[j]) / 2.0
            if abs(F_node) > 1e-10:
                f.write(f"FK,{j + 1},FZ,{F_node:.6f}    ! y={self.y[j]:.3f}m\n")
        f.write("\n")

        # --- My torque distributed to both spars ---
        # Torque is reacted by a couple: F_chord * spar_separation
        # Split proportionally by local bending stiffness, but for
        # simplicity use 50/50 as vertical couple forces on the two spars.
        spar_sep = self.x_rear - self.x_main  # chordwise separation [m]
        f.write("! --- Applied torque (My) as vertical couple on both spars ---\n")
        for j in range(nn):
            if j == 0:
                M_node = self.my_torque[j] * dy[0] / 2.0
            elif j == nn - 1:
                M_node = self.my_torque[j] * dy[-1] / 2.0
            else:
                M_node = self.my_torque[j] * (dy[j - 1] + dy[j]) / 2.0
            if abs(M_node) > 1e-10 and abs(spar_sep[j]) > 1e-6:
                Fz_couple = M_node / spar_sep[j]
                # +Fz on main, -Fz on rear (positive My → nose-up)
                kp_main = j + 1
                kp_rear = nn + j + 1
                f.write(f"FK,{kp_main},FZ,{Fz_couple:.6f}    ! Torque couple, y={self.y[j]:.3f}m\n")
                f.write(f"FK,{kp_rear},FZ,{-Fz_couple:.6f}\n")
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
        f.write("PLNSOL,U,Z         ! Plot Z-deflection (flapwise)\n")
        f.write("PLNSOL,U,X         ! Plot X-deflection (chordwise)\n")
        f.write("PRESOL,SMISC       ! Beam element results\n")
        f.write("ETABLE,VONM,S,EQV  ! Von Mises stress\n")
        f.write("FINISH\n")

    # ==================================================================
    # Workbench External Data CSV
    # ==================================================================

    def write_workbench_csv(self, path: str | Path) -> Path:
        """Write dual-spar geometry + loads as CSV for ANSYS Workbench."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import csv

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
                    # Flags
                    "Is_Joint", "Is_Wire_Attach",
                ]
                writer.writerow(header)

                joint_set = set(self.joint_node_indices)
                wire_set = set(self.wire_nodes)

                for j in range(self.nn):
                    writer.writerow([
                        j + 1,
                        f"{self.y[j]:.8e}",
                        f"{self.x_main[j]:.8e}", f"{self.z_main[j]:.8e}",
                        f"{self.R_main[j]:.8e}", f"{self.t_main[j]:.8e}",
                        f"{self.x_rear[j]:.8e}", f"{self.z_rear[j]:.8e}",
                        f"{self.R_rear[j]:.8e}", f"{self.t_rear[j]:.8e}",
                        f"{self.fz_lift[j]:.8e}", f"{self.my_torque[j]:.8e}",
                        1 if j in joint_set else 0,
                        1 if j in wire_set else 0,
                    ])

            logger.info("Workbench CSV written to %s", path)
        except Exception:
            logger.exception("Failed to write Workbench CSV to %s", path)
            raise
        return path

    # ==================================================================
    # NASTRAN Bulk Data (.bdf)
    # ==================================================================

    def write_nastran_bdf(self, path: str | Path) -> Path:
        """Write a NASTRAN BDF with CBAR elements + MPC rigid links."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w") as f:
                self._bdf_write(f)
            logger.info("NASTRAN BDF written to %s", path)
        except Exception:
            logger.exception("Failed to write NASTRAN BDF to %s", path)
            raise
        return path

    def _bdf_write(self, f: TextIO) -> None:
        nn = self.nn
        n_elem = nn - 1
        dy = np.diff(self.y)

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
            f.write("$ --- Rigid rib links (RBE2) ---\n")
            rbe_id = 2 * n_elem + 1
            for idx in self.joint_node_indices:
                main_gid = idx + 1
                rear_gid = nn + idx + 1
                # RBE2: independent = main, dependent = rear, all 6 DOFs
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

        # -- Applied loads --
        # Fz lift on main spar
        f.write("$ --- Lift forces on main spar ---\n")
        for j in range(nn):
            if j == 0:
                F_node = self.fz_lift[j] * dy[0] / 2.0
            elif j == nn - 1:
                F_node = self.fz_lift[j] * dy[-1] / 2.0
            else:
                F_node = self.fz_lift[j] * (dy[j - 1] + dy[j]) / 2.0
            if abs(F_node) > 1e-10:
                direction = 1.0 if F_node > 0 else -1.0
                f.write(f"FORCE,1,{j + 1},,{abs(F_node):.6f},0.0,0.0,{direction}\n")

        # My torque as vertical couple
        spar_sep = self.x_rear - self.x_main
        f.write("$ --- Torque as vertical couple on both spars ---\n")
        for j in range(nn):
            if j == 0:
                M_node = self.my_torque[j] * dy[0] / 2.0
            elif j == nn - 1:
                M_node = self.my_torque[j] * dy[-1] / 2.0
            else:
                M_node = self.my_torque[j] * (dy[j - 1] + dy[j]) / 2.0
            if abs(M_node) > 1e-10 and abs(spar_sep[j]) > 1e-6:
                Fz_couple = M_node / spar_sep[j]
                # Main spar
                d1 = 1.0 if Fz_couple > 0 else -1.0
                f.write(f"FORCE,1,{j + 1},,{abs(Fz_couple):.6f},0.0,0.0,{d1}\n")
                # Rear spar (opposite sign)
                d2 = -d1
                f.write(f"FORCE,1,{nn + j + 1},,{abs(Fz_couple):.6f},0.0,0.0,{d2}\n")

        f.write("ENDDATA\n")
