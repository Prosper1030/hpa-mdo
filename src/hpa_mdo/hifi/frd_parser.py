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


def parse_buckle_eigenvalues(dat_path: str | Path) -> list[float]:
    """Parse CalculiX BUCKLE eigenvalues from a ``.dat`` text file."""

    eigenvalues: list[float] = []
    in_eigen_table = False

    for raw in Path(dat_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue

        upper = stripped.upper()
        if "EIGENVALUE" in upper:
            in_eigen_table = True
            direct = _direct_eigenvalue(stripped)
            if direct is not None:
                eigenvalues.append(direct)
            continue

        if not in_eigen_table:
            continue

        values = _numeric_tokens(stripped)
        if len(values) >= 2 and _looks_like_mode_number(values[0]):
            eigenvalues.append(values[1])
        elif not values and eigenvalues:
            in_eigen_table = False

    return eigenvalues


def _numeric_tokens(line: str) -> list[float]:
    return [
        float(token.replace("D", "E"))
        for token in re.findall(
            r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?",
            line,
        )
    ]


def _direct_eigenvalue(line: str) -> float | None:
    match = re.search(
        r"EIGENVALUE(?:\s+NUMBER)?\s*\d*\s*(?:=|:)\s*"
        r"([-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?)",
        line,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return float(match.group(1).replace("D", "E"))


def _looks_like_mode_number(value: float) -> bool:
    return value >= 0.0 and abs(value - round(value)) < 1.0e-9
