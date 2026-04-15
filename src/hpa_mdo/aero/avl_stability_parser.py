"""Parse AVL `.st` stability-derivative output.

AVL writes a Fortran fixed-width block of coefficients and derivatives.
Two traps to avoid:

1. Very large negative numbers can eat the leading whitespace so that
   two columns abut each other (``0.04321-12.01234``).  We therefore
   match each ``<name> = <value>`` pair with a regex, **not**
   ``str.split()``.

2. AVL labels control derivatives by the d-index it assigned at
   runtime (``Cmd01``, ``Cnd02``, …), **not** by the CONTROL name
   declared in the ``.avl``.  We build a ``control_name -> d_index``
   mapping either from a column header line in the ``.st`` itself or
   — as a fallback — from the order of ``CONTROL`` declarations in the
   ``.avl`` geometry file.

Unit convention (AVL):
    alpha / beta / rate derivatives   ->  per radian
    control-surface derivatives       ->  per radian of deflection

AVL reports control-surface derivatives in **per radian** when the
``.avl`` gain is unity (the default), so the parser returns everything
consistently in ``1/rad``.  Callers that want ``1/deg`` must convert
explicitly with ``math.radians``.

The parser is defensive: any field that cannot be located is returned
as ``math.nan`` and the dataclass remains instantiable so downstream
consumers can still produce a state-space matrix with holes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# --------------------------------------------------------------------------
# Regex helpers
# --------------------------------------------------------------------------

# Fortran float token — tolerates "-12.01234" glued to the preceding
# whitespace or even to the previous column.  The leading "\b" ensures
# we do not match inside another identifier.
_FLOAT_TOKEN = r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?"

# Matches ``<name> = <value>`` pairs where <name> is an AVL coefficient
# or derivative identifier.  Allows trailing apostrophes (``Cl'``) and
# digits (``CLd01``).  We drop the trailing apostrophe in post-processing.
_PAIR_RE = re.compile(
    rf"(?P<name>[A-Za-z][A-Za-z0-9_]*)'?\s*=\s*(?P<value>{_FLOAT_TOKEN})"
)

# Column-header line such as:
#     elevator     d01     rudder       d02
# Captures alternating ``name  dNN`` pairs.
_CTRL_HEADER_RE = re.compile(r"([A-Za-z][A-Za-z0-9_\-]*)\s+d(\d{1,3})")


# --------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------


def _nan() -> float:
    return math.nan


@dataclass
class StabilityDerivatives:
    """Container for AVL ``.st`` derivatives in a single trim case.

    All derivatives are in 1/rad; angles in the trim state are in
    degrees (matching AVL's convention).  Lengths are in the reference
    frame declared in the ``.avl`` (typically metres for this project).
    """

    # Trim state
    alpha_trim_deg: float = field(default_factory=_nan)
    beta_trim_deg: float = field(default_factory=_nan)
    CL_trim: float = field(default_factory=_nan)
    CD_trim: float = field(default_factory=_nan)
    Cm_trim: float = field(default_factory=_nan)

    # Reference geometry / flight condition
    Sref: float = field(default_factory=_nan)
    bref: float = field(default_factory=_nan)
    cref: float = field(default_factory=_nan)
    Xref: float = field(default_factory=_nan)
    Yref: float = field(default_factory=_nan)
    Zref: float = field(default_factory=_nan)
    mach: float = field(default_factory=_nan)

    # Longitudinal derivatives (1/rad)
    CL_alpha: float = field(default_factory=_nan)
    CD_alpha: float = field(default_factory=_nan)
    Cm_alpha: float = field(default_factory=_nan)
    CL_q: float = field(default_factory=_nan)
    Cm_q: float = field(default_factory=_nan)

    # Control authority — longitudinal
    CL_de: float = field(default_factory=_nan)
    Cm_de: float = field(default_factory=_nan)

    # Lateral-directional derivatives (1/rad)
    CY_beta: float = field(default_factory=_nan)
    Cl_beta: float = field(default_factory=_nan)
    Cn_beta: float = field(default_factory=_nan)
    CY_p: float = field(default_factory=_nan)
    Cl_p: float = field(default_factory=_nan)
    Cn_p: float = field(default_factory=_nan)
    CY_r: float = field(default_factory=_nan)
    Cl_r: float = field(default_factory=_nan)
    Cn_r: float = field(default_factory=_nan)

    # Control authority — lateral-directional
    CY_da: float = field(default_factory=_nan)
    Cl_da: float = field(default_factory=_nan)
    Cn_da: float = field(default_factory=_nan)
    CY_dr: float = field(default_factory=_nan)
    Cl_dr: float = field(default_factory=_nan)
    Cn_dr: float = field(default_factory=_nan)

    # Book-keeping / provenance
    control_mapping: Dict[str, int] = field(default_factory=dict)
    source_path: Optional[str] = None
    raw_derivatives: Dict[str, float] = field(default_factory=dict)

    # ----------------------------------------------------------------
    # Convenience
    # ----------------------------------------------------------------
    def as_flat_dict(self) -> Dict[str, float]:
        """Flatten to a JSON-friendly dict (controls mapping included)."""
        out: Dict[str, float] = {}
        for fld in fields(self):
            if fld.name in ("control_mapping", "source_path", "raw_derivatives"):
                continue
            out[fld.name] = float(getattr(self, fld.name))
        return out


# --------------------------------------------------------------------------
# Control-mapping helpers
# --------------------------------------------------------------------------


def _parse_control_mapping_from_st_text(text: str) -> Dict[str, int]:
    """Scan the ``.st`` for the ``elevator d01 rudder d02`` header line."""
    mapping: Dict[str, int] = {}
    for line in text.splitlines():
        # Skip derivative lines (they contain '=')
        if "=" in line:
            continue
        for name, idx_text in _CTRL_HEADER_RE.findall(line):
            try:
                mapping.setdefault(name.strip(), int(idx_text))
            except ValueError:
                continue
    return mapping


def parse_control_mapping_from_avl(avl_path: Path) -> Dict[str, int]:
    """Walk the ``.avl`` geometry file and record CONTROL declaration order.

    The first CONTROL encountered becomes d1, the second d2, and so on.
    Duplicate CONTROL declarations of the same surface (each SECTION
    re-declares it) are de-duplicated by first appearance.
    """
    mapping: Dict[str, int] = {}
    next_index = 1
    try:
        text = avl_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return mapping

    lines = [ln.rstrip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if line.strip().upper() != "CONTROL":
            continue
        if i + 1 >= len(lines):
            continue
        tokens = lines[i + 1].split()
        if not tokens:
            continue
        name = tokens[0]
        if name in mapping:
            continue
        mapping[name] = next_index
        next_index += 1
    return mapping


# --------------------------------------------------------------------------
# Main parser
# --------------------------------------------------------------------------


def _scan_pairs(text: str) -> Dict[str, float]:
    """Return the last value seen for each key — AVL prints each once."""
    pairs: Dict[str, float] = {}
    for match in _PAIR_RE.finditer(text):
        name = match.group("name")
        value_text = match.group("value")
        try:
            pairs[name] = float(value_text)
        except ValueError:
            continue
    return pairs


def _pick(pairs: Dict[str, float], *keys: str) -> float:
    """Return the first key present in `pairs`, else NaN."""
    for key in keys:
        if key in pairs:
            return float(pairs[key])
    return math.nan


def _control_field(
    pairs: Dict[str, float],
    coef_prefix: str,
    d_index: Optional[int],
) -> float:
    if d_index is None:
        return math.nan
    # AVL can emit either d1 or d01 depending on layout — try both.
    candidates = (
        f"{coef_prefix}d{d_index}",
        f"{coef_prefix}d{d_index:02d}",
        f"{coef_prefix}d{d_index:03d}",
    )
    for key in candidates:
        if key in pairs:
            return float(pairs[key])
    return math.nan


def parse_st_text(
    text: str,
    *,
    source_path: Optional[Path] = None,
    control_mapping_override: Optional[Dict[str, int]] = None,
) -> StabilityDerivatives:
    """Parse an AVL ``.st`` text blob into :class:`StabilityDerivatives`.

    Parameters
    ----------
    text:
        Contents of an AVL ``.st`` stability-derivative file.
    source_path:
        Optional original path (stored on the result for provenance).
    control_mapping_override:
        If provided, use this ``control_name -> d_index`` mapping
        instead of scanning the ``.st`` header.  Useful when the
        mapping is known from the ``.avl`` geometry file.
    """

    pairs = _scan_pairs(text)

    if control_mapping_override is not None:
        control_mapping = dict(control_mapping_override)
    else:
        control_mapping = _parse_control_mapping_from_st_text(text)

    # Control indices for the three standard axes.  HPA baselines may
    # only wire elevator + rudder (no aileron); we therefore accept
    # missing entries and emit NaN for the corresponding derivatives.
    elevator_idx = _find_ctrl_index(control_mapping, ("elevator", "ELEVATOR", "Elevator"))
    aileron_idx = _find_ctrl_index(control_mapping, ("aileron", "AILERON", "Aileron"))
    rudder_idx = _find_ctrl_index(control_mapping, ("rudder", "RUDDER", "Rudder"))

    derivs = StabilityDerivatives(
        # Trim state — AVL prints Alpha, Beta in degrees in the .st header.
        alpha_trim_deg=_pick(pairs, "Alpha"),
        beta_trim_deg=_pick(pairs, "Beta"),
        CL_trim=_pick(pairs, "CLtot"),
        CD_trim=_pick(pairs, "CDtot"),
        Cm_trim=_pick(pairs, "Cmtot"),
        # Reference geometry / Mach
        Sref=_pick(pairs, "Sref"),
        bref=_pick(pairs, "Bref"),
        cref=_pick(pairs, "Cref"),
        Xref=_pick(pairs, "Xref"),
        Yref=_pick(pairs, "Yref"),
        Zref=_pick(pairs, "Zref"),
        mach=_pick(pairs, "Mach"),
        # Longitudinal
        CL_alpha=_pick(pairs, "CLa"),
        CD_alpha=_pick(pairs, "CDa"),
        Cm_alpha=_pick(pairs, "Cma"),
        CL_q=_pick(pairs, "CLq"),
        Cm_q=_pick(pairs, "Cmq"),
        # Lateral-directional
        CY_beta=_pick(pairs, "CYb"),
        Cl_beta=_pick(pairs, "Clb"),
        Cn_beta=_pick(pairs, "Cnb"),
        CY_p=_pick(pairs, "CYp"),
        Cl_p=_pick(pairs, "Clp"),
        Cn_p=_pick(pairs, "Cnp"),
        CY_r=_pick(pairs, "CYr"),
        Cl_r=_pick(pairs, "Clr"),
        Cn_r=_pick(pairs, "Cnr"),
        # Controls — elevator
        CL_de=_control_field(pairs, "CL", elevator_idx),
        Cm_de=_control_field(pairs, "Cm", elevator_idx),
        # Controls — aileron
        CY_da=_control_field(pairs, "CY", aileron_idx),
        Cl_da=_control_field(pairs, "Cl", aileron_idx),
        Cn_da=_control_field(pairs, "Cn", aileron_idx),
        # Controls — rudder
        CY_dr=_control_field(pairs, "CY", rudder_idx),
        Cl_dr=_control_field(pairs, "Cl", rudder_idx),
        Cn_dr=_control_field(pairs, "Cn", rudder_idx),
        control_mapping=control_mapping,
        source_path=str(source_path) if source_path else None,
        raw_derivatives=dict(pairs),
    )
    return derivs


def parse_st_file(
    path: Path,
    *,
    control_mapping_override: Optional[Dict[str, int]] = None,
) -> StabilityDerivatives:
    """Parse an AVL ``.st`` file on disk.

    Missing file raises ``FileNotFoundError``; empty / malformed files
    return a :class:`StabilityDerivatives` full of NaNs.
    """

    text = path.read_text(encoding="utf-8", errors="ignore")
    return parse_st_text(
        text,
        source_path=path,
        control_mapping_override=control_mapping_override,
    )


def _find_ctrl_index(
    mapping: Dict[str, int],
    candidates: Iterable[str],
) -> Optional[int]:
    """Case-insensitive lookup in the control mapping."""
    if not mapping:
        return None
    lower = {k.lower(): v for k, v in mapping.items()}
    for cand in candidates:
        if cand in mapping:
            return int(mapping[cand])
        idx = lower.get(cand.lower())
        if idx is not None:
            return int(idx)
    return None


__all__ = [
    "StabilityDerivatives",
    "parse_st_text",
    "parse_st_file",
    "parse_control_mapping_from_avl",
]
