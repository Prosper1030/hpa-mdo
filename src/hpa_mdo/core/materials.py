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
    poisson_ratio: float = 0.3
    description: str = ""

    @property
    def sigma_c(self) -> float:
        return self.compressive_strength if self.compressive_strength else self.tensile_strength


# Default location of the database file
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "materials.yaml"


class MaterialDB:
    """Load materials from an external YAML file."""

    def __init__(self, path: Optional[Path] = None):
        self._db: dict[str, Material] = {}
        db_path = path or _DEFAULT_DB_PATH
        if db_path.exists():
            self._load(db_path)

    def _load(self, path: Path) -> None:
        with open(path) as f:
            raw = yaml.safe_load(f)
        for key, props in raw.items():
            self._db[key] = Material(
                name=props.get("name", key),
                E=float(props["E"]),
                G=float(props["G"]) if "G" in props else float(props["E"]) / (2 * (1 + float(props.get("poisson_ratio", 0.3)))),
                density=float(props["density"]),
                tensile_strength=float(props["tensile_strength"]),
                compressive_strength=float(props["compressive_strength"]) if props.get("compressive_strength") else None,
                poisson_ratio=float(props.get("poisson_ratio", 0.3)),
                description=props.get("description", ""),
            )

    def get(self, key: str) -> Material:
        if key not in self._db:
            available = ", ".join(sorted(self._db))
            raise KeyError(f"Material '{key}' not found. Available: {available}")
        return self._db[key]

    def register(self, key: str, material: Material) -> None:
        self._db[key] = material

    def list_materials(self) -> list:
        return sorted(self._db.keys())

    def as_dict(self) -> dict:
        return {k: v.__dict__ for k, v in self._db.items()}
