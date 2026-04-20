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

import logging
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from hpa_mdo.aero.base import AeroParser, SpanwiseLoad

LOGGER = logging.getLogger(__name__)


class VSPAeroParser(AeroParser):
    """Parse VSPAero `.lod` and `.polar` output files."""
    _CACHE_MAX_SIZE = 32
    _parse_cache: "OrderedDict[tuple[str, int, tuple[int, ...] | None], list[SpanwiseLoad]]" = OrderedDict()

    def __init__(
        self,
        lod_path,
        polar_path=None,
        component_ids: list[int] | None = None,
    ):
        self.lod_path = Path(lod_path)
        self.polar_path = Path(polar_path) if polar_path else None
        self.component_ids = (
            None
            if component_ids is None
            else tuple(sorted({int(component_id) for component_id in component_ids}))
        )
        self._cases: list[SpanwiseLoad] = []
        self._warned_multi_component = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, **kwargs) -> List[SpanwiseLoad]:
        """Parse the .lod file and return one SpanwiseLoad per AoA case."""
        cache_key = self._cache_key(self.lod_path, self.component_ids)
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
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        header_idx = None
        for idx, line in enumerate(lines):
            tokens = line.split()
            if self._looks_like_polar_header(tokens):
                header_idx = idx
                break
        if header_idx is None:
            raise ValueError(f"Could not find VSPAero .polar header row in {self.polar_path}")

        header = lines[header_idx].split()
        rows = []
        for line in lines[header_idx + 1:]:
            values = line.split()
            if len(values) != len(header):
                continue
            rows.append(values)
        df = pd.DataFrame(rows, columns=header).astype(float)
        return df

    # ------------------------------------------------------------------
    # Internal parsing helpers
    # ------------------------------------------------------------------

    @classmethod
    def _cache_key(
        cls,
        file_path: Path,
        component_ids: tuple[int, ...] | None,
    ) -> tuple[str, int, tuple[int, ...] | None]:
        st = os.stat(file_path)
        return str(file_path.resolve()), int(st.st_mtime_ns), component_ids

    @classmethod
    def _cache_get(
        cls,
        key: tuple[str, int, tuple[int, ...] | None],
    ) -> Optional[list[SpanwiseLoad]]:
        cached = cls._parse_cache.get(key)
        if cached is not None:
            cls._parse_cache.move_to_end(key)
        return cached

    @classmethod
    def _cache_put(
        cls,
        key: tuple[str, int, tuple[int, ...] | None],
        cases: list[SpanwiseLoad],
    ) -> None:
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

    # Reference-scalar lines look like `Sref_ 35.175 Lunit^2`. The key must
    # start with a letter so that numeric data rows (e.g. `5  1  1  0.68 ...`)
    # are not mistaken for reference scalars.
    _REF_SCALAR_RE = re.compile(r"([A-Za-z][\w]*_?)\s+([-\d.]+)")

    # Legacy 16-column layout defaults, used only when a named header row is
    # not present in a given block:
    # Wing, S, Xavg, Yavg, Zavg, Chord, V/Vref, Cl, Cd, Cs, Cx, Cy, Cz, Cmx, Cmy, Cmz
    _LEGACY_COLUMN_DEFAULTS: dict[str, int] = {
        "component": 0,
        "yavg": 3,
        "chord": 5,
        "cl": 7,
        "cd": 8,
        "cmy": 14,
    }

    # Candidate names (in priority order) used to locate each logical column
    # from a named header row. Supports both the legacy `Wing S Xavg ...` and
    # the OpenVSP 3.45.3 `Iter VortexSheet TrailVort Xavg Yavg Zavg dSpan
    # SoverB Chord dArea V/Vref Cl Cd Cs ...` format.
    _COLUMN_NAME_CANDIDATES: dict[str, tuple[str, ...]] = {
        "component": ("wing", "vortexsheet"),
        "yavg": ("yavg",),
        "chord": ("chord",),
        "cl": ("cl",),
        "cd": ("cd",),
        "cmy": ("cmy",),
    }

    @staticmethod
    def _looks_like_polar_header(tokens: list[str]) -> bool:
        if not tokens:
            return False
        lowered = {token.lower() for token in tokens}
        return "aoa" in lowered and "cltot" in lowered and "cdtot" in lowered

    @staticmethod
    def _parse_header(block: str) -> dict:
        """Extract reference values (Sref, Cref, Bref, Mach, AoA, Rho, Vinf)."""
        ref: dict = {}
        for line in block.splitlines():
            # Match lines like: Sref_     35.1750000 Lunit^2
            m = VSPAeroParser._REF_SCALAR_RE.match(line.strip())
            if m:
                key = m.group(1).rstrip("_").lower()
                try:
                    ref[key] = float(m.group(2))
                except ValueError:
                    continue
        return ref

    @staticmethod
    def _looks_like_column_header(tokens: list[str]) -> bool:
        """Return True if ``tokens`` looks like the `.lod` data column-name row.

        Both the legacy and OpenVSP 3.45.3 formats start the strip-force data
        table with a non-numeric header row that contains ``Chord``. The first
        token is always non-numeric (``Wing`` in legacy, ``Iter`` in 3.45.3).
        """
        if not tokens:
            return False
        try:
            float(tokens[0])
        except ValueError:
            pass
        else:
            return False
        lowered = {t.lower() for t in tokens}
        return "chord" in lowered and "cl" in lowered

    @classmethod
    def _resolve_column_indices(
        cls, column_index: dict[str, int]
    ) -> dict[str, int]:
        """Map logical columns (yavg/chord/cl/...) to integer indices."""
        resolved: dict[str, int] = {}
        for logical, candidates in cls._COLUMN_NAME_CANDIDATES.items():
            for candidate in candidates:
                if candidate in column_index:
                    resolved[logical] = column_index[candidate]
                    break
            else:
                resolved[logical] = cls._LEGACY_COLUMN_DEFAULTS[logical]
        return resolved

    def _parse_one_case(self, block: str, ref_defaults: dict) -> Optional[SpanwiseLoad]:
        """Parse a single AoA case block from the .lod file."""
        lines = block.splitlines()

        # Re-parse per-case reference header (AoA may differ between blocks)
        # and look for the named column-name header that begins the data table.
        ref = dict(ref_defaults)
        data_start = 0
        column_index: dict[str, int] = {}
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            tokens = stripped.split()
            if self._looks_like_column_header(tokens):
                column_index = {tok.lower(): idx for idx, tok in enumerate(tokens)}
                data_start = i + 1
                break
            m = self._REF_SCALAR_RE.match(stripped)
            if m:
                key = m.group(1).rstrip("_").lower()
                try:
                    ref[key] = float(m.group(2))
                except ValueError:
                    continue

        if data_start == 0:
            # Fallback: find the first numeric-only data row. We also leave
            # ``column_index`` empty so that the legacy 16-column defaults
            # apply below.
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

        cols = self._resolve_column_indices(column_index)
        min_cols = max(cols.values()) + 1

        # Parse strip-force data rows
        rows = []
        for line in lines[data_start:]:
            parts = line.split()
            if len(parts) < min_cols:
                continue
            try:
                row = [float(x) for x in parts]
                rows.append(row)
            except ValueError:
                continue

        if not rows:
            return None

        data_df = pd.DataFrame(rows)
        comp_col = cols["component"]
        component_values = data_df.iloc[:, comp_col].to_numpy(dtype=float)
        component_ids_detected = tuple(sorted({int(round(value)) for value in component_values}))
        if self.component_ids is None and len(component_ids_detected) > 1 and not self._warned_multi_component:
            LOGGER.warning(
                "VSPAeroParser detected multiple component IDs in %s with no component filter: %s; "
                "parsed loads may mix multiple surfaces.",
                self.lod_path,
                ", ".join(str(component_id) for component_id in component_ids_detected),
            )
            self._warned_multi_component = True
        if self.component_ids is not None:
            filter_ids = {float(component_id) for component_id in self.component_ids}
            data_df = data_df[data_df.iloc[:, comp_col].isin(filter_ids)]
            if data_df.empty:
                return None

        data = data_df.to_numpy(dtype=float)
        y_all = data[:, cols["yavg"]]
        chord = data[:, cols["chord"]]
        cl = data[:, cols["cl"]]
        cd = data[:, cols["cd"]]
        cm = data[:, cols["cmy"]]

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
