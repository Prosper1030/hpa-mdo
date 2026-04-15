"""Parsers for small pieces of CalculiX ASCII output."""
from __future__ import annotations

from pathlib import Path
import re

import numpy as np


def parse_displacement(frd_path: str | Path, *, node_set: str = "ALL") -> np.ndarray:
    """Parse the last CalculiX ``DISP`` block into ``[nid, ux, uy, uz]`` rows."""

    _ = node_set
    rows: list[list[float]] = []
    current_rows: list[list[float]] = []
    in_disp = False

    for raw in Path(frd_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("-4") and "DISP" in upper:
            in_disp = True
            current_rows = []
            continue
        if in_disp and upper.startswith("-4"):
            in_disp = False
            if current_rows:
                rows = current_rows
            continue
        if not in_disp:
            continue
        if stripped.startswith("-3"):
            in_disp = False
            if current_rows:
                rows = current_rows
            continue
        if stripped.startswith("-1"):
            values = _numeric_tokens(stripped)
            if len(values) >= 5:
                current_rows.append([values[1], values[2], values[3], values[4]])

    if not rows:
        return np.empty((0, 4), dtype=float)
    return np.asarray(rows, dtype=float)


def _numeric_tokens(line: str) -> list[float]:
    return [
        float(token.replace("D", "E"))
        for token in re.findall(
            r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?",
            line,
        )
    ]
