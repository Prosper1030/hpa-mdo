"""Parser for XFLR5 exported data.

XFLR5 can export spanwise distributions as CSV/TXT from its
Operating Point analysis.  This parser handles several common formats:

1. Wing Operating Point → Export → Spanwise Data (.csv)
2. Wing Polar → Export (.csv)
3. Direct XFLR5 project XML (partial support)

Usage:
    parser = XFLR5Parser("wing_oppoint.csv")
    loads = parser.parse()
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import numpy as np
import pandas as pd

from hpa_mdo.aero.base import AeroParser, SpanwiseLoad


class XFLR5Parser(AeroParser):
    """Parse XFLR5 exported CSV/TXT spanwise distributions."""

    # Common XFLR5 column name variations
    _Y_COLS = ["y-span", "y", "y (m)", "y_span", "yspan", "span"]
    _CHORD_COLS = ["chord", "chord (m)", "c"]
    _CL_COLS = ["cl", "cl_local", "cl local", "icl", "cl_strip"]
    _CD_COLS = ["cd", "cd_local", "cd local", "icd", "cdp", "cd_strip"]
    _CM_COLS = ["cm", "cm_local", "cm local"]

    def __init__(
        self,
        csv_path: Union[str, Path],
        velocity: float = 6.5,
        air_density: float = 1.225,
    ):
        self.csv_path = Path(csv_path)
        self.velocity = velocity
        self.air_density = air_density
        self._cases: List[SpanwiseLoad] = []

    def parse(self, **kwargs) -> List[SpanwiseLoad]:
        """Auto-detect format and parse."""
        text = self.csv_path.read_text(encoding="utf-8", errors="replace")

        # XFLR5 uses comma or tab separators
        if "\t" in text.splitlines()[0]:
            df = pd.read_csv(self.csv_path, sep="\t", skipinitialspace=True)
        else:
            df = pd.read_csv(self.csv_path, skipinitialspace=True)

        df.columns = [c.strip().lower() for c in df.columns]

        y = self._find_col(df, self._Y_COLS)
        chord = self._find_col(df, self._CHORD_COLS)
        cl = self._find_col(df, self._CL_COLS)
        cd = self._find_col(df, self._CD_COLS, allow_missing=True)
        cm = self._find_col(df, self._CM_COLS, allow_missing=True)

        if cd is None:
            cd = np.zeros_like(y)
        if cm is None:
            cm = np.zeros_like(y)

        # Take only positive y (right half-span)
        mask = y >= 0
        y, chord, cl, cd, cm = y[mask], chord[mask], cl[mask], cd[mask], cm[mask]
        order = np.argsort(y)
        y, chord, cl, cd, cm = y[order], chord[order], cl[order], cd[order], cm[order]

        q = 0.5 * self.air_density * self.velocity ** 2

        sl = SpanwiseLoad(
            y=y,
            chord=chord,
            cl=cl,
            cd=cd,
            cm=cm,
            lift_per_span=q * chord * cl,
            drag_per_span=q * chord * cd,
            aoa_deg=kwargs.get("aoa_deg", 0.0),
            velocity=self.velocity,
            dynamic_pressure=q,
        )
        self._cases = [sl]
        return self._cases

    def get_load_at_aoa(self, aoa_deg: float) -> SpanwiseLoad:
        if not self._cases:
            self.parse(aoa_deg=aoa_deg)
        return min(self._cases, key=lambda c: abs(c.aoa_deg - aoa_deg))

    @staticmethod
    def _find_col(
        df: pd.DataFrame, candidates: List[str], allow_missing: bool = False
    ) -> Optional[np.ndarray]:
        for name in candidates:
            if name in df.columns:
                return df[name].to_numpy(dtype=float)
        if allow_missing:
            return None
        raise KeyError(f"Could not find column. Tried: {candidates}. Available: {list(df.columns)}")
