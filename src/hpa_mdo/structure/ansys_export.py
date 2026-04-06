"""Export optimised spar geometry and loads to ANSYS-compatible formats.

Supported formats:
    1. ANSYS APDL macro (.mac) — for ANSYS Mechanical APDL
    2. Workbench External Data CSV — for ANSYS Workbench import
    3. NASTRAN bulk data (.bdf) — readable by ANSYS and other FEA tools

The exported model includes:
    - Beam elements (BEAM188/189) along the half-span
    - Cross-section data (SECTYPE/SECDATA for hollow circular tube)
    - Material properties (MP,EX / MP,DENS / MP,PRXY)
    - Boundary conditions (fixed root)
    - Applied loads (distributed lift minus weight)
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

import numpy as np

from hpa_mdo.structure.beam_model import BeamResult
from hpa_mdo.structure.spar import TubularSpar
from hpa_mdo.core.materials import Material


class ANSYSExporter:
    """Generate ANSYS input files from HPA-MDO results."""

    def __init__(
        self,
        spar: TubularSpar,
        spar_props: dict,
        beam_result: BeamResult,
        material: Material,
    ):
        self.spar = spar
        self.props = spar_props
        self.result = beam_result
        self.material = material

    # ------------------------------------------------------------------
    # APDL macro
    # ------------------------------------------------------------------

    def write_apdl(self, path: str | Path) -> Path:
        """Write ANSYS APDL macro file (.mac)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        y = self.spar.y
        d_o = self.spar.outer_diameter
        d_i = self.props["inner_diameter"]
        f_ext = self.result.f_ext
        n = len(y)

        with open(path, "w") as f:
            self._write_apdl_header(f)
            self._write_apdl_material(f)
            self._write_apdl_geometry(f, y, d_o, d_i, n)
            self._write_apdl_mesh(f, n)
            self._write_apdl_bc(f)
            self._write_apdl_loads(f, y, f_ext, n)
            self._write_apdl_solve(f)

        return path

    def _write_apdl_header(self, f: TextIO) -> None:
        f.write("! ============================================================\n")
        f.write("! HPA-MDO: Auto-generated ANSYS APDL input\n")
        f.write(f"! Material: {self.material.name}\n")
        f.write(f"! Spar nodes: {len(self.spar.y)}\n")
        f.write("! ============================================================\n")
        f.write("/PREP7\n\n")

    def _write_apdl_material(self, f: TextIO) -> None:
        f.write("! --- Material properties ---\n")
        f.write(f"MP,EX,1,{self.material.E:.6e}    ! Young's modulus [Pa]\n")
        f.write(f"MP,DENS,1,{self.material.density:.1f}    ! Density [kg/m³]\n")
        f.write(f"MP,PRXY,1,{self.material.poisson_ratio:.3f}    ! Poisson ratio\n\n")

    def _write_apdl_geometry(
        self, f: TextIO, y: np.ndarray, d_o: np.ndarray, d_i: np.ndarray, n: int
    ) -> None:
        f.write("! --- Element type: BEAM188 (Timoshenko beam) ---\n")
        f.write("ET,1,BEAM188\n")
        f.write("KEYOPT,1,1,0    ! Warping DOF excluded\n")
        f.write("KEYOPT,1,3,2    ! Cubic shape functions\n\n")

        f.write("! --- Keypoints (nodes along half-span) ---\n")
        for j in range(n):
            f.write(f"K,{j+1}, 0.0, {y[j]:.6f}, 0.0\n")
        f.write("\n")

        f.write("! --- Lines connecting keypoints ---\n")
        for j in range(n - 1):
            f.write(f"L,{j+1},{j+2}\n")
        f.write("\n")

        # Section definitions — one per element with tapered OD/ID
        f.write("! --- Cross-sections (hollow circular tube) ---\n")
        for j in range(n - 1):
            sec_id = j + 1
            r_o = (d_o[j] + d_o[j + 1]) / 4.0  # average for element
            r_i = (d_i[j] + d_i[j + 1]) / 4.0
            f.write(f"SECTYPE,{sec_id},BEAM,CTUBE\n")
            f.write(f"SECDATA,{r_i:.6f},{r_o:.6f}\n")
        f.write("\n")

    def _write_apdl_mesh(self, f: TextIO, n: int) -> None:
        f.write("! --- Mesh: one element per line segment ---\n")
        f.write("MAT,1\n")
        for j in range(n - 1):
            f.write(f"LSEL,S,LINE,,{j+1}\n")
            f.write(f"LATT,1,,1,,,,{j+1}    ! MAT=1, TYPE=1, SECNUM={j+1}\n")
            f.write("LESIZE,ALL,,,1\n")
            f.write("LMESH,ALL\n")
        f.write("ALLSEL,ALL\n\n")

    def _write_apdl_bc(self, f: TextIO) -> None:
        f.write("! --- Boundary conditions: fixed root ---\n")
        f.write("DK,1,ALL,0    ! Fix all DOF at root keypoint\n\n")

    def _write_apdl_loads(
        self, f: TextIO, y: np.ndarray, f_ext: np.ndarray, n: int
    ) -> None:
        f.write("! --- Applied loads (distributed force → nodal forces) ---\n")
        f.write("! Converting distributed load to equivalent nodal forces\n")
        dy = np.diff(y)
        for j in range(n):
            if j == 0:
                F_node = f_ext[0] * dy[0] / 2.0
            elif j == n - 1:
                F_node = f_ext[-1] * dy[-1] / 2.0
            else:
                F_node = f_ext[j] * (dy[j - 1] + dy[j]) / 2.0
            if abs(F_node) > 1e-10:
                f.write(f"FK,{j+1},FZ,{F_node:.6f}    ! Node {j+1}, y={y[j]:.3f}m\n")
        f.write("\n")

    def _write_apdl_solve(self, f: TextIO) -> None:
        f.write("! --- Solution ---\n")
        f.write("FINISH\n")
        f.write("/SOLU\n")
        f.write("ANTYPE,STATIC\n")
        f.write("SOLVE\n")
        f.write("FINISH\n\n")
        f.write("! --- Post-processing ---\n")
        f.write("/POST1\n")
        f.write("SET,LAST\n")
        f.write("PLNSOL,U,Z    ! Plot Z-deflection\n")
        f.write("PRESOL,SMISC  ! List beam element results\n")
        f.write("FINISH\n")

    # ------------------------------------------------------------------
    # Workbench External Data CSV
    # ------------------------------------------------------------------

    def write_workbench_csv(self, path: str | Path) -> Path:
        """Write geometry + loads as CSV importable by ANSYS Workbench."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        import pandas as pd

        y = self.spar.y
        d_o = self.spar.outer_diameter
        d_i = self.props["inner_diameter"]
        wall = self.props["wall_thickness"]
        f_ext = self.result.f_ext
        defl = self.result.deflection
        stress = self.result.stress * self.material.E

        df = pd.DataFrame({
            "Y_Position_m": y,
            "Outer_Diameter_m": d_o,
            "Inner_Diameter_m": d_i,
            "Wall_Thickness_m": wall,
            "Force_Per_Span_N_m": f_ext,
            "Deflection_m": defl,
            "Bending_Stress_Pa": stress,
        })

        df.to_csv(path, index=False, float_format="%.8e")
        return path

    # ------------------------------------------------------------------
    # NASTRAN Bulk Data (.bdf)
    # ------------------------------------------------------------------

    def write_nastran_bdf(self, path: str | Path) -> Path:
        """Write a NASTRAN bulk data file (.bdf) for the spar beam model."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        y = self.spar.y
        d_o = self.spar.outer_diameter
        d_i = self.props["inner_diameter"]
        f_ext = self.result.f_ext
        n = len(y)
        dy = np.diff(y)

        with open(path, "w") as f:
            f.write("$ HPA-MDO: Auto-generated NASTRAN Bulk Data\n")
            f.write("BEGIN BULK\n")

            # Material (MAT1)
            f.write(f"MAT1,1,{self.material.E:.4e},{self.material.E/(2*(1+self.material.poisson_ratio)):.4e},"
                    f"{self.material.poisson_ratio},{self.material.density}\n")

            # Grid points
            for j in range(n):
                f.write(f"GRID,{j+1},,0.0,{y[j]:.6f},0.0\n")

            # Beam elements (CBAR) with PBARL hollow tube
            for j in range(n - 1):
                eid = j + 1
                pid = j + 1
                r_o = (d_o[j] + d_o[j + 1]) / 4.0
                r_i = (d_i[j] + d_i[j + 1]) / 4.0
                f.write(f"PBARL,{pid},1,,TUBE\n")
                f.write(f",{r_o:.6f},{r_o - r_i:.6f}\n")
                f.write(f"CBAR,{eid},{pid},{j+1},{j+2},0.0,0.0,1.0\n")

            # Fixed root
            f.write("SPC1,1,123456,1\n")

            # Nodal forces
            for j in range(n):
                if j == 0:
                    F_node = f_ext[0] * dy[0] / 2.0
                elif j == n - 1:
                    F_node = f_ext[-1] * dy[-1] / 2.0
                else:
                    F_node = f_ext[j] * (dy[j - 1] + dy[j]) / 2.0
                if abs(F_node) > 1e-10:
                    f.write(f"FORCE,1,{j+1},,{abs(F_node):.6f},0.0,0.0,{1.0 if F_node > 0 else -1.0}\n")

            f.write("ENDDATA\n")

        return path
