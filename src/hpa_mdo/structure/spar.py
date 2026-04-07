"""DEPRECATED: This module (v1 parametric spar model) is no longer used.
It will be removed in a future release. Do not import.

Parametric tubular spar model.

Defines the cross-section geometry (hollow circular tube) and computes
structural properties (I, EI, mass) as functions of the design variables
(inner diameters at root and tip) that the optimizer will adjust.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hpa_mdo.core.materials import Material


@dataclass
class SparSection:
    """Cross-section properties at a single spanwise station."""
    y: float              # spanwise position [m]
    outer_diameter: float # [m]
    inner_diameter: float # [m]
    material: Material

    @property
    def outer_radius(self) -> float:
        return self.outer_diameter / 2.0

    @property
    def inner_radius(self) -> float:
        return self.inner_diameter / 2.0

    @property
    def wall_thickness(self) -> float:
        return (self.outer_diameter - self.inner_diameter) / 2.0

    @property
    def area(self) -> float:
        """Cross-sectional area [m²]."""
        return np.pi / 4 * (self.outer_diameter**2 - self.inner_diameter**2)

    @property
    def I_xx(self) -> float:
        """Second moment of area [m⁴]."""
        return np.pi / 64 * (self.outer_diameter**4 - self.inner_diameter**4)

    @property
    def EI(self) -> float:
        """Flexural rigidity [N·m²]."""
        return self.material.E * self.I_xx

    @property
    def mass_per_length(self) -> float:
        """Linear mass density [kg/m]."""
        return self.material.density * self.area


class TubularSpar:
    """Parametric carbon-fiber tubular spar spanning the half-wing.

    Design variables:
        - d_i_root : inner diameter at root [m]
        - d_i_tip  : inner diameter at tip [m]

    The outer diameter is determined by the airfoil thickness at each
    spanwise station (from the wing geometry config).
    """

    def __init__(
        self,
        y: np.ndarray,
        outer_diameter: np.ndarray,
        material: Material,
        min_wall_thickness: float = 0.8e-3,
    ):
        """
        Parameters
        ----------
        y : (N,) array
            Spanwise node positions [m].
        outer_diameter : (N,) array
            Outer diameter at each node [m], from airfoil geometry.
        material : Material
            Spar tube material.
        min_wall_thickness : float
            Manufacturing constraint on minimum wall thickness [m].
        """
        self.y = y
        self.outer_diameter = outer_diameter
        self.material = material
        self.min_wall_thickness = min_wall_thickness
        self.n_nodes = len(y)

    def compute(self, d_i_root: float, d_i_tip: float) -> dict[str, np.ndarray]:
        """Evaluate spar properties for given design variables.

        Parameters
        ----------
        d_i_root : float
            Inner diameter at root [m].
        d_i_tip : float
            Inner diameter at tip [m].

        Returns
        -------
        dict with:
            'inner_diameter' : (N,) array [m]
            'wall_thickness' : (N,) array [m]
            'I_xx'           : (N,) array [m⁴]
            'EI'             : (N,) array [N·m²]
            'mass_per_length': (N,) array [kg/m]
            'total_mass'     : float [kg]
            'outer_radius'   : (N,) array [m]
            'sections'       : list[SparSection]
        """
        eta = (self.y - self.y[0]) / (self.y[-1] - self.y[0])
        d_i = d_i_root + eta * (d_i_tip - d_i_root)

        # Enforce: inner diameter <= outer diameter - 2 * min_wall_thickness
        d_i = np.minimum(d_i, self.outer_diameter - 2 * self.min_wall_thickness)
        d_i = np.maximum(d_i, 0.0)  # non-negative

        d_o = self.outer_diameter
        wall = (d_o - d_i) / 2.0
        area = np.pi / 4 * (d_o**2 - d_i**2)
        I_xx = np.pi / 64 * (d_o**4 - d_i**4)
        EI = self.material.E * I_xx
        mass_per_length = self.material.density * area
        total_mass = float(np.trapz(mass_per_length, self.y))

        sections = [
            SparSection(
                y=float(self.y[j]),
                outer_diameter=float(d_o[j]),
                inner_diameter=float(d_i[j]),
                material=self.material,
            )
            for j in range(self.n_nodes)
        ]

        return {
            "inner_diameter": d_i,
            "wall_thickness": wall,
            "I_xx": I_xx,
            "EI": EI,
            "mass_per_length": mass_per_length,
            "total_mass": total_mass,
            "outer_radius": d_o / 2.0,
            "sections": sections,
        }

    def design_variable_bounds(self) -> list[tuple[float, float]]:
        """Return (lower, upper) bounds for [d_i_root, d_i_tip]."""
        # Lower bound: OD - 2*max_wall = leave some tube
        # Upper bound: OD - 2*min_wall = thinnest allowed
        d_o_root = float(self.outer_diameter[0])
        d_o_tip = float(self.outer_diameter[-1])
        min_t = self.min_wall_thickness

        return [
            (0.0, d_o_root - 2 * min_t),    # d_i_root
            (0.0, d_o_tip - 2 * min_t),      # d_i_tip
        ]

    @classmethod
    def from_wing_geometry(cls, wing, spar_cfg, material: Material) -> TubularSpar:
        """Build a TubularSpar from WingGeometry and SparConfig."""
        # Outer diameter from airfoil thickness
        airfoil_thickness_m = wing.airfoil_thickness * wing.chord

        if spar_cfg.outer_diameter_root is not None:
            d_o_root = spar_cfg.outer_diameter_root
            d_o_tip = spar_cfg.outer_diameter_tip or d_o_root * 0.5
            eta = (wing.y - wing.y[0]) / (wing.y[-1] - wing.y[0])
            outer_d = d_o_root + eta * (d_o_tip - d_o_root)
        else:
            frac_root = spar_cfg.thickness_fraction_root
            frac_tip = spar_cfg.thickness_fraction_tip
            eta = (wing.y - wing.y[0]) / (wing.y[-1] - wing.y[0])
            frac = frac_root + eta * (frac_tip - frac_root)
            outer_d = frac * airfoil_thickness_m

        return cls(
            y=wing.y,
            outer_diameter=outer_d,
            material=material,
            min_wall_thickness=spar_cfg.min_wall_thickness,
        )
