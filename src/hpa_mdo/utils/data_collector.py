"""Append optimisation input/output data to a CSV database after each run.

The collected data feeds future surrogate-model training (Gaussian
process, neural net, etc.) by storing every configuration + result pair
in a flat CSV that is easy to load with pandas.

Usage
-----
    from hpa_mdo.utils.data_collector import DataCollector

    collector = DataCollector("database/training_data.csv")
    collector.record(cfg, opt_result, aero_info={"aoa_deg": 3.5, "total_lift_N": 940.0})
    df = collector.load()
"""
from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from hpa_mdo.core.config import HPAConfig
from hpa_mdo.structure.optimizer import OptimizationResult

# Fixed number of segment columns (pad with NaN if fewer segments)
_N_SEG = 6

COLUMNS = [
    "timestamp",
    "project_name",
    # Flight / safety
    "velocity",
    "air_density",
    "aero_load_factor",
    "material_safety_factor",
    # Planform
    "span",
    "root_chord",
    "tip_chord",
    # Materials
    "main_spar_material",
    "rear_spar_material",
    # Design variables — main spar thicknesses [mm]
    *[f"main_t_seg_{i+1}" for i in range(_N_SEG)],
    # Design variables — rear spar thicknesses [mm]
    *[f"rear_t_seg_{i+1}" for i in range(_N_SEG)],
    # Objectives / responses
    "total_mass_full_kg",
    "spar_mass_full_kg",
    "tip_deflection_m",
    "twist_max_deg",
    "max_stress_main_MPa",
    "max_stress_rear_MPa",
    "failure_index",
    # Optional aero info
    "aoa_deg",
    "total_lift_N",
]


class DataCollector:
    """Append one row per optimisation run to a CSV training database."""

    def __init__(self, db_path: str = "database/training_data.csv") -> None:
        self.db_path = Path(db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        cfg: HPAConfig,
        opt_result: OptimizationResult,
        aero_info: Optional[dict] = None,
    ) -> Path:
        """Append one row to the training data CSV.

        Columns include:
        - timestamp
        - project_name
        - velocity, air_density, aero_load_factor, material_safety_factor
        - span, root_chord, tip_chord
        - main_spar_material, rear_spar_material
        - main_t_seg_1..6 (mm), rear_t_seg_1..6 (mm)
        - total_mass_full_kg, spar_mass_full_kg
        - tip_deflection_m, twist_max_deg
        - max_stress_main_MPa, max_stress_rear_MPa
        - failure_index
        - aoa_deg, total_lift_N (from aero_info if available)

        Parameters
        ----------
        cfg : HPAConfig
            Configuration used for the run.
        opt_result : OptimizationResult
            Output of SparOptimizer.optimize().
        aero_info : dict, optional
            Extra aerodynamic data.  Expected keys:
            ``aoa_deg`` (float) and ``total_lift_N`` (float).

        Returns
        -------
        Path
            The path to the CSV file that was written.
        """
        if aero_info is None:
            aero_info = {}

        row = self._build_row(cfg, opt_result, aero_info)

        file_exists = self.db_path.exists() and self.db_path.stat().st_size > 0
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.db_path, "a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        return self.db_path

    def load(self) -> pd.DataFrame:
        """Load the training database as a DataFrame."""
        if not self.db_path.exists():
            return pd.DataFrame(columns=COLUMNS)
        return pd.read_csv(self.db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pad_segments(arr: Optional[np.ndarray], n: int = _N_SEG) -> list:
        """Return a list of length *n*, padding with NaN if needed."""
        if arr is None:
            return [float("nan")] * n
        vals = list(arr.ravel()[:n])
        while len(vals) < n:
            vals.append(float("nan"))
        return vals

    def _build_row(
        self,
        cfg: HPAConfig,
        res: OptimizationResult,
        aero: dict,
    ) -> dict:
        main_t = self._pad_segments(res.main_t_seg_mm)
        rear_t = self._pad_segments(res.rear_t_seg_mm)

        row: dict = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            ),
            "project_name": cfg.project_name,
            # Flight / safety
            "velocity": cfg.flight.velocity,
            "air_density": cfg.flight.air_density,
            "aero_load_factor": cfg.safety.aerodynamic_load_factor,
            "material_safety_factor": cfg.safety.material_safety_factor,
            # Planform
            "span": cfg.wing.span,
            "root_chord": cfg.wing.root_chord,
            "tip_chord": cfg.wing.tip_chord,
            # Materials
            "main_spar_material": cfg.main_spar.material,
            "rear_spar_material": cfg.rear_spar.material,
        }

        # Segment thicknesses [mm]
        for i in range(_N_SEG):
            row[f"main_t_seg_{i+1}"] = main_t[i]
            row[f"rear_t_seg_{i+1}"] = rear_t[i]

        # Objectives / responses
        row["total_mass_full_kg"] = res.total_mass_full_kg
        row["spar_mass_full_kg"] = res.spar_mass_full_kg
        row["tip_deflection_m"] = res.tip_deflection_m
        row["twist_max_deg"] = res.twist_max_deg
        row["max_stress_main_MPa"] = res.max_stress_main_Pa / 1e6
        row["max_stress_rear_MPa"] = res.max_stress_rear_Pa / 1e6
        row["failure_index"] = res.failure_index

        # Optional aero data
        row["aoa_deg"] = aero.get("aoa_deg", float("nan"))
        row["total_lift_N"] = aero.get("total_lift_N", float("nan"))

        return row
