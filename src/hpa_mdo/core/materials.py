"""Material property database — loaded from external YAML.

NO materials are hardcoded.  Everything comes from data/materials.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class Material:
    name: str
    E: float               # Young's modulus [Pa]
    G: float               # Shear modulus [Pa]
    density: float          # [kg/m³]
    tensile_strength: float # UTS [Pa]
    compressive_strength: Optional[float] = None
    shear_strength: Optional[float] = None   # in-plane shear failure strength [Pa]
    tension_only: Optional[bool] = None      # True = member carries tension only (e.g. cables)
    poisson_ratio: float = 0.3
    description: str = ""
    # Tsai-Wu / Tsai-Hill lamina strength parameters (optional; CFRP only)
    F1t: Optional[float] = None  # longitudinal tensile strength  [Pa]
    F1c: Optional[float] = None  # longitudinal compressive strength [Pa]
    F2t: Optional[float] = None  # transverse tensile strength    [Pa]
    F2c: Optional[float] = None  # transverse compressive strength [Pa]
    F6:  Optional[float] = None  # in-plane shear strength        [Pa]

    @property
    def sigma_c(self) -> float:
        return self.compressive_strength if self.compressive_strength else self.tensile_strength


@dataclass(frozen=True)
class PlyMaterial:
    """Single ply (lamina) properties for CLT."""

    name: str
    E1: float
    E2: float
    G12: float
    nu12: float
    t_ply: float
    density: float
    F1t: float
    F1c: float
    F2t: float
    F2c: float
    F6: float

    @property
    def nu21(self) -> float:
        return self.nu12 * self.E2 / self.E1


# Default location of the database file
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "materials.yaml"


class MaterialDB:
    """Load materials from an external YAML file."""

    def __init__(self, path: Optional[Path] = None):
        self._materials: dict[str, Material] = {}
        self._ply_materials: dict[str, PlyMaterial] = {}
        db_path = path or _DEFAULT_DB_PATH
        if db_path.exists():
            self._load(db_path)

    def _load(self, path: Path) -> None:
        with open(path) as f:
            raw = yaml.safe_load(f)
        for key, props in raw.items():
            if props.get("material_type") == "composite_ply" or "E1" in props:
                self._ply_materials[key] = PlyMaterial(
                    name=props.get("name", key),
                    E1=float(props["E1"]),
                    E2=float(props["E2"]),
                    G12=float(props["G12"]),
                    nu12=float(props["nu12"]),
                    t_ply=float(props["t_ply"]),
                    density=float(props["density"]),
                    F1t=float(props["F1t"]),
                    F1c=float(props["F1c"]),
                    F2t=float(props["F2t"]),
                    F2c=float(props["F2c"]),
                    F6=float(props["F6"]),
                )
                continue

            self._materials[key] = Material(
                name=props.get("name", key),
                E=float(props["E"]),
                G=float(props["G"]) if props.get("G") is not None else (
                    float(props["E"]) / (2 * (1 + float(props.get("poisson_ratio") or 0.3)))
                ),
                density=float(props["density"]),
                tensile_strength=float(props["tensile_strength"]),
                compressive_strength=float(props["compressive_strength"])
                if props.get("compressive_strength")
                else None,
                shear_strength=float(props["shear_strength"])
                if props.get("shear_strength")
                else None,
                tension_only=bool(props["tension_only"])
                if props.get("tension_only") is not None
                else None,
                poisson_ratio=float(props["poisson_ratio"])
                if props.get("poisson_ratio") is not None
                else 0.3,
                description=props.get("description", ""),
                F1t=float(props["F1t"]) if props.get("F1t") is not None else None,
                F1c=float(props["F1c"]) if props.get("F1c") is not None else None,
                F2t=float(props["F2t"]) if props.get("F2t") is not None else None,
                F2c=float(props["F2c"]) if props.get("F2c") is not None else None,
                F6=float(props["F6"]) if props.get("F6") is not None else None,
            )

    def get(self, key: str) -> Material:
        if key not in self._materials:
            available = ", ".join(sorted(self._materials))
            raise KeyError(f"Material '{key}' not found. Available: {available}")
        return self._materials[key]

    def get_ply(self, key: str) -> PlyMaterial:
        """Load a composite ply material by key."""
        if key not in self._ply_materials:
            available = ", ".join(sorted(self._ply_materials))
            raise KeyError(f"Ply material '{key}' not found. Available: {available}")
        return self._ply_materials[key]

    def register(self, key: str, material: Material) -> None:
        self._materials[key] = material

    def __contains__(self, key: str) -> bool:
        return key in self._materials

    def keys(self):
        return self._materials.keys()

    def list_materials(self) -> list:
        return sorted(self._materials.keys())

    def list_ply_materials(self) -> list[str]:
        return sorted(self._ply_materials.keys())

    def as_dict(self) -> dict:
        return {k: v.__dict__ for k, v in self._materials.items()}
