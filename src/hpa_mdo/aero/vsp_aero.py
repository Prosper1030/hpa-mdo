"""Parser for OpenVSP / VSPAero output files.

Reads the `.lod` (spanwise load distribution) and `.polar` (integrated
force coefficients) files produced by VSPAero and converts them into
the framework's SpanwiseLoad objects.

Supported workflow:
    1. User runs VSPAero from the OpenVSP GUI or Python API.
    2. This parser ingests the results for structural analysis.
    3. Optionally, VSP Python API calls can be automated (see `run_vspaero`).
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from hpa_mdo.aero.base import AeroParser, SpanwiseLoad


class VSPAeroParser(AeroParser):
    """Parse VSPAero `.lod` and `.polar` output files."""
    _CACHE_MAX_SIZE = 32
    _parse_cache: "OrderedDict[tuple[str, int], list[SpanwiseLoad]]" = OrderedDict()

    def __init__(self, lod_path, polar_path=None):
        self.lod_path = Path(lod_path)
        self.polar_path = Path(polar_path) if polar_path else None
        self._cases: list[SpanwiseLoad] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, **kwargs) -> List[SpanwiseLoad]:
        """Parse the .lod file and return one SpanwiseLoad per AoA case."""
        cache_key = self._cache_key(self.lod_path)
        cached = self._cache_get(cache_key)
        if cached is not None:
            self._cases = cached
            return cached

        raw_text = self.lod_path.read_text()
        header_block, data_blocks = self._split_cases(raw_text)
        ref = self._parse_header(header_block)

        self._cases = []
        for block in data_blocks:
            sl = self._parse_one_case(block, ref)
            if sl is not None:
                self._cases.append(sl)

        self._cache_put(cache_key, self._cases)
        return self._cases

    def get_load_at_aoa(self, aoa_deg: float) -> SpanwiseLoad:
        """Return the case closest to the requested AoA."""
        if not self._cases:
            self.parse()
        best = min(self._cases, key=lambda c: abs(c.aoa_deg - aoa_deg))
        return best

    def get_polar_df(self) -> Optional[pd.DataFrame]:
        """Parse the .polar file into a DataFrame (if provided)."""
        if self.polar_path is None or not self.polar_path.exists():
            return None
        text = self.polar_path.read_text()
        lines = [line for line in text.strip().splitlines() if line.strip()]
        header = lines[0].split()
        rows = [line.split() for line in lines[1:]]
        df = pd.DataFrame(rows, columns=header).astype(float)
        return df

    # ------------------------------------------------------------------
    # Internal parsing helpers
    # ------------------------------------------------------------------

    @classmethod
    def _cache_key(cls, file_path: Path) -> tuple[str, int]:
        st = os.stat(file_path)
        return str(file_path.resolve()), int(st.st_mtime_ns)

    @classmethod
    def _cache_get(cls, key: tuple[str, int]) -> Optional[list[SpanwiseLoad]]:
        cached = cls._parse_cache.get(key)
        if cached is not None:
            cls._parse_cache.move_to_end(key)
        return cached

    @classmethod
    def _cache_put(cls, key: tuple[str, int], cases: list[SpanwiseLoad]) -> None:
        cls._parse_cache[key] = cases
        cls._parse_cache.move_to_end(key)
        while len(cls._parse_cache) > cls._CACHE_MAX_SIZE:
            cls._parse_cache.popitem(last=False)

    @staticmethod
    def _split_cases(text: str) -> Tuple[str, List[str]]:
        """Split the .lod file into the header block and per-AoA data blocks.

        VSPAero .lod files contain a header with reference values repeated
        for each AoA case, separated by lines of asterisks.
        """
        blocks = re.split(r"\*{10,}", text)
        blocks = [b.strip() for b in blocks if b.strip()]

        # Each block starts with a header section (Name/Value/Units table)
        # followed by the strip-force data table.  The first block's header
        # gives us the reference values; every subsequent block is a new case.
        header = blocks[0] if blocks else ""
        return header, blocks

    @staticmethod
    def _parse_header(block: str) -> dict:
        """Extract reference values (Sref, Cref, Bref, Mach, AoA, Rho, Vinf)."""
        ref: dict = {}
        for line in block.splitlines():
            line = line.strip()
            # Match lines like: Sref_     35.1750000 Lunit^2
            m = re.match(r"(\w+_?)\s+([-\d.]+)", line)
            if m:
                key = m.group(1).rstrip("_").lower()
                ref[key] = float(m.group(2))
        return ref

    def _parse_one_case(self, block: str, ref_defaults: dict) -> Optional[SpanwiseLoad]:
        """Parse a single AoA case block from the .lod file."""
        lines = block.splitlines()

        # Re-parse per-case reference header (AoA may differ between blocks)
        ref = dict(ref_defaults)
        data_start = 0
        for i, line in enumerate(lines):
            m = re.match(r"\s*(\w+_?)\s+([-\d.]+)", line)
            if m and not line.strip().startswith("Wing"):
                key = m.group(1).rstrip("_").lower()
                ref[key] = float(m.group(2))
            if "Wing" in line and "Cl" in line:
                data_start = i + 1
                break

        if data_start == 0:
            # Try to find data rows by looking for numeric-only lines
            for i, line in enumerate(lines):
                parts = line.split()
                if len(parts) >= 10:
                    try:
                        float(parts[0])
                        data_start = i
                        break
                    except ValueError:
                        continue

        if data_start == 0:
            return None

        # Parse strip-force data rows
        rows = []
        for line in lines[data_start:]:
            parts = line.split()
            if len(parts) < 10:
                continue
            try:
                row = [float(x) for x in parts]
                rows.append(row)
            except ValueError:
                continue

        if not rows:
            return None

        data = np.array(rows)
        # VSPAero .lod columns (typical):
        # Wing, S, Xavg, Yavg, Zavg, Chord, V/Vref, Cl, Cd, Cs, Cx, Cy, Cz, Cmx, Cmy, Cmz
        # Index:  0    1     2     3     4      5       6   7   8   9  10  11  12   13   14   15

        y_all = data[:, 3]     # Yavg
        chord = data[:, 5]     # Chord
        cl = data[:, 7]        # Cl
        cd = data[:, 8]        # Cd
        cm = data[:, 14]       # Cmy (pitching moment)

        # Take only one side (positive y = right half-span)
        mask = y_all >= 0
        y = y_all[mask]
        chord = chord[mask]
        cl = cl[mask]
        cd = cd[mask]
        cm = cm[mask]

        # Sort by y
        order = np.argsort(y)
        y = y[order]
        chord = chord[order]
        cl = cl[order]
        cd = cd[order]
        cm = cm[order]

        # Compute dimensional loads
        aoa = ref.get("aoa", 0.0)
        rho = ref.get("rho", 1.225)
        vinf = ref.get("vinf", 100.0)
        q = 0.5 * rho * vinf ** 2
        lift_per_span = q * chord * cl
        drag_per_span = q * chord * cd

        return SpanwiseLoad(
            y=y,
            chord=chord,
            cl=cl,
            cd=cd,
            cm=cm,
            lift_per_span=lift_per_span,
            drag_per_span=drag_per_span,
            aoa_deg=aoa,
            velocity=vinf,
            dynamic_pressure=q,
        )
