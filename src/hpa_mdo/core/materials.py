"""Material property database.

Provides a registry of structural materials. Users can add custom materials
at runtime via the API or by extending the YAML config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Material:
    """Isotropic or quasi-isotropic material properties."""
    name: str
    E: float              # Young's modulus [Pa]
    density: float        # Density [kg/m³]
    tensile_strength: float   # Ultimate tensile strength [Pa]
    compressive_strength: Optional[float] = None  # If None, assumed = tensile
    poisson_ratio: float = 0.3
    description: str = ""

    @property
    def sigma_c(self) -> float:
        return self.compressive_strength if self.compressive_strength else self.tensile_strength


class MaterialDB:
    """In-memory material database with built-in HPA-relevant entries."""

    _BUILTIN: dict[str, Material] = {
        "carbon_fiber_hm": Material(
            name="High-Modulus Carbon Fiber (unidirectional)",
            E=230e9,
            density=1600.0,
            tensile_strength=2500e6,
            compressive_strength=1500e6,
            poisson_ratio=0.27,
            description="Typical HM CF tube, e.g. Toray M46J",
        ),
        "carbon_fiber_std": Material(
            name="Standard-Modulus Carbon Fiber",
            E=135e9,
            density=1550.0,
            tensile_strength=1800e6,
            compressive_strength=1200e6,
            poisson_ratio=0.30,
            description="T300/T700 class CF",
        ),
        "aluminum_6061_t6": Material(
            name="Aluminum 6061-T6",
            E=68.9e9,
            density=2700.0,
            tensile_strength=310e6,
            compressive_strength=310e6,
            poisson_ratio=0.33,
        ),
        "balsa": Material(
            name="Balsa Wood (structural grade)",
            E=3.4e9,
            density=160.0,
            tensile_strength=20e6,
            compressive_strength=12e6,
            poisson_ratio=0.23,
        ),
        "kevlar_49": Material(
            name="Kevlar 49",
            E=112e9,
            density=1440.0,
            tensile_strength=3000e6,
            poisson_ratio=0.36,
        ),
        "steel_4130": Material(
            name="4130 Chromoly Steel",
            E=205e9,
            density=7850.0,
            tensile_strength=670e6,
            compressive_strength=670e6,
            poisson_ratio=0.29,
            description="Common for landing gear and fittings",
        ),
    }

    def __init__(self) -> None:
        self._db: dict[str, Material] = dict(self._BUILTIN)

    def get(self, key: str) -> Material:
        if key not in self._db:
            available = ", ".join(sorted(self._db))
            raise KeyError(f"Material '{key}' not found. Available: {available}")
        return self._db[key]

    def register(self, key: str, material: Material) -> None:
        self._db[key] = material

    def list_materials(self) -> list[str]:
        return sorted(self._db.keys())

    def as_dict(self) -> dict[str, dict]:
        """Serialise the full DB for API responses."""
        return {k: v.__dict__ for k, v in self._db.items()}
