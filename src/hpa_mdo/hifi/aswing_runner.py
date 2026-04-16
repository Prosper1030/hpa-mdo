"""ASWING nonlinear aeroelastic runner (M-ASWING).

Orchestrates:
  1. Export an ASWING ``.asw`` seed file via ``aswing_exporter.export_aswing``.
  2. Drive ASWING in batch mode (stdin pipe) to obtain a trim solution.
  3. Parse stdout for tip deflection, tip twist, CL, alpha, and whether the
     trim converged.

No ASWING installation is required to import this module.  All entry points
return a result dict and never raise (errors surfaced via the ``"error"`` key).

ASWING batch command sequence used
------------------------------------
  load <asw_path>
  oper
  v <vinf>           set airspeed
  d                  set density / use ISA sea-level (if needed)
  trim               solve nonlinear trim
  .                  print current state to stdout
  quit

Output parsing
--------------
ASWING stdout mixes interactive prompts with numeric output.  Key patterns::

    CLtot =   1.2345    alpha =  10.98  deg
    CL =   1.23  CD =  0.017  CM =  -0.082
    Tip deflection  uz =  2.341 m   twist = -0.501 deg

Because ASWING output format varies between sub-releases we apply defensive
regex that returns ``None`` on parse failure rather than raising.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional

from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.logging import get_logger

logger = get_logger(__name__)

# ── Result dict keys ────────────────────────────────────────────────────────
# All values are float or None; "error" key is str or None.
#
# {
#   "tip_deflection_m"  : float | None,
#   "tip_twist_deg"     : float | None,
#   "CL_trim"           : float | None,
#   "alpha_trim_deg"    : float | None,
#   "CM_trim"           : float | None,
#   "converged"         : bool,
#   "stdout"            : str,
#   "error"             : str | None,
# }

_RESULT_TEMPLATE: Dict[str, Any] = {
    "tip_deflection_m": None,
    "tip_twist_deg": None,
    "CL_trim": None,
    "alpha_trim_deg": None,
    "CM_trim": None,
    "converged": False,
    "stdout": "",
    "error": None,
}

# ── Regex patterns for ASWING stdout ────────────────────────────────────────

# Trim solution convergence marker
_RE_CONVERGED = re.compile(r"(?i)(trim\s+converged|solution\s+converged|dResidual\s*=\s*[\d.e+\-]+)")

# Global force coefficients:  CLtot =  1.2345  alpha = 10.98  deg
_RE_CL = re.compile(r"CLtot\s*=\s*([-\d.eE+]+)")
_RE_ALPHA = re.compile(r"alpha\s*=\s*([-\d.eE+]+)\s*deg", re.IGNORECASE)
_RE_CM = re.compile(r"CM(?:tot)?\s*=\s*([-\d.eE+]+)")

# Station table — last data line is the tip station.
# ASWING prints station tables with columns like:
#   iw   t    X      Y      Z     Chord  Twist   CL
# We capture Z (tip vertical deflection) and Twist (tip aeroelastic twist).
#
# The table header line always ends with "CL" or "Cm"; data lines start with
# an integer beam index, then a float t-coordinate.
_RE_STATION_HEADER = re.compile(
    r"iw\s+t\s+X\s+Y\s+Z\s+Chord\s+Twist", re.IGNORECASE
)
_RE_STATION_DATA = re.compile(
    r"^\s*(\d+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)"
    r"\s+([-\d.eE+]+)\s+([-\d.eE+]+)"
)

# Tip deflection reported explicitly (some ASWING builds):
#   Tip deflection  uz =  2.341 m   twist = -0.501 deg
_RE_TIP_UZ = re.compile(r"uz\s*=\s*([-\d.eE+]+)\s*m", re.IGNORECASE)
_RE_TIP_TWIST = re.compile(r"twist\s*=\s*([-\d.eE+]+)\s*deg", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def find_aswing(cfg: Optional[HPAConfig] = None) -> Optional[str]:
    """Return path to ``aswing`` binary or *None* if not found.

    Search order:
    1. ``cfg.hi_fidelity.aswing.binary`` if set.
    2. System PATH via ``shutil.which("aswing")``.
    """
    if cfg is not None:
        configured = cfg.hi_fidelity.aswing.binary
        if configured and Path(configured).is_file():
            return configured

    found = shutil.which("aswing")
    return found  # None if not on PATH


def run_aswing(
    asw_path: Path | str,
    cfg: HPAConfig,
    *,
    timeout_s: Optional[int] = None,
    aswing_binary: Optional[str] = None,
) -> Dict[str, Any]:
    """Run ASWING in batch mode and return a result dict.

    Parameters
    ----------
    asw_path : Path
        Path to the ``.asw`` geometry file to load.
    cfg : HPAConfig
        Project configuration (provides flight velocity, density, and runner
        settings from ``cfg.hi_fidelity.aswing``).
    timeout_s : int, optional
        Override ``cfg.hi_fidelity.aswing.timeout_s``.
    aswing_binary : str, optional
        Override binary path (takes precedence over config + PATH search).

    Returns
    -------
    dict  — see module docstring for key schema.  Never raises.
    """
    result: Dict[str, Any] = dict(_RESULT_TEMPLATE)

    # ── Locate binary ──────────────────────────────────────────────────────
    binary = aswing_binary or find_aswing(cfg)
    if binary is None:
        result["error"] = (
            "ASWING binary not found.  Install ASWING and set "
            "hi_fidelity.aswing.binary in configs/blackcat_004.yaml, "
            "or add 'aswing' to PATH."
        )
        logger.warning(result["error"])
        return result

    # ── Build batch commands ───────────────────────────────────────────────
    asw_path = Path(asw_path).resolve()
    aw_cfg = cfg.hi_fidelity.aswing
    vinf = aw_cfg.vinf_mps if aw_cfg.vinf_mps is not None else cfg.flight.velocity
    t_out = timeout_s if timeout_s is not None else aw_cfg.timeout_s

    # ASWING batch stdin: commands separated by newlines.
    # "." in oper mode prints the current solution state (deflections, CL, etc.)
    batch_cmds = textwrap.dedent(f"""\
        load {asw_path}
        oper
        v {vinf:.6g}
        trim
        .
        quit
    """)

    logger.info("Running ASWING: %s  (V=%.2f m/s)", asw_path.name, vinf)

    # ── Execute ────────────────────────────────────────────────────────────
    try:
        proc = subprocess.run(
            [binary],
            input=batch_cmds,
            capture_output=True,
            text=True,
            timeout=t_out,
        )
        stdout = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        result["error"] = f"ASWING timed out after {t_out} s."
        logger.error(result["error"])
        return result
    except FileNotFoundError:
        result["error"] = f"ASWING binary not executable: {binary!r}"
        logger.error(result["error"])
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"ASWING subprocess error: {exc}"
        logger.error(result["error"])
        return result

    result["stdout"] = stdout
    _parse_stdout(stdout, result)

    if result["error"] is None and not result["converged"]:
        logger.warning(
            "ASWING ran but trim convergence was not detected in stdout. "
            "Check result['stdout'] for details."
        )

    logger.info(
        "ASWING result: uz=%.3f m  twist=%.3f deg  CL=%.4f  alpha=%.3f deg  converged=%s",
        result["tip_deflection_m"] or float("nan"),
        result["tip_twist_deg"] or float("nan"),
        result["CL_trim"] or float("nan"),
        result["alpha_trim_deg"] or float("nan"),
        result["converged"],
    )
    return result


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------

def _parse_stdout(stdout: str, result: Dict[str, Any]) -> None:
    """Fill *result* in-place by regex-scanning *stdout*."""

    # ── Convergence ────────────────────────────────────────────────────────
    if _RE_CONVERGED.search(stdout):
        result["converged"] = True

    # ── Global coefficients ────────────────────────────────────────────────
    m = _RE_CL.search(stdout)
    if m:
        result["CL_trim"] = float(m.group(1))
        if _RE_CONVERGED.search(stdout):
            result["converged"] = True  # CL present → trim ran

    m = _RE_ALPHA.search(stdout)
    if m:
        result["alpha_trim_deg"] = float(m.group(1))

    m = _RE_CM.search(stdout)
    if m:
        result["CM_trim"] = float(m.group(1))

    # ── Tip deflection / twist (explicit line) ─────────────────────────────
    m = _RE_TIP_UZ.search(stdout)
    if m:
        result["tip_deflection_m"] = float(m.group(1))

    m = _RE_TIP_TWIST.search(stdout)
    if m:
        result["tip_twist_deg"] = float(m.group(1))

    # ── Station table scan (fallback if explicit line absent) ──────────────
    if result["tip_deflection_m"] is None or result["tip_twist_deg"] is None:
        _parse_station_table(stdout, result)

    # ── Return-code anomaly ────────────────────────────────────────────────
    # (result["error"] left None — binary ran; partial parse is expected
    #  when ASWING cannot trim to the requested CL/velocity.)


def _parse_station_table(stdout: str, result: Dict[str, Any]) -> None:
    """Scan all ASWING station tables; use the *last* row of the *last* table.

    ASWING may print intermediate iteration tables before the final converged
    solution.  We scan every table and keep the final tip row so that the
    converged solution overwrites any intermediate iteration values.
    """
    lines = stdout.splitlines()
    in_table = False
    current_last_row: Optional[re.Match] = None
    final_last_row: Optional[re.Match] = None

    for line in lines:
        if _RE_STATION_HEADER.search(line):
            # New table starts — commit any previous table's last row
            if current_last_row is not None:
                final_last_row = current_last_row
            in_table = True
            current_last_row = None
            continue
        if not in_table:
            continue
        m = _RE_STATION_DATA.match(line)
        if m:
            current_last_row = m
        elif current_last_row is not None and line.strip() == "":
            # Blank line after data → table ended; commit and reset
            final_last_row = current_last_row
            current_last_row = None
            in_table = False

    # Flush any trailing table without a blank line terminator
    if current_last_row is not None:
        final_last_row = current_last_row

    if final_last_row is not None:
        # Columns: iw(1) t(2) X(3) Y(4) Z(5) Chord(6) Twist(7)
        if result["tip_deflection_m"] is None:
            result["tip_deflection_m"] = float(final_last_row.group(5))
        if result["tip_twist_deg"] is None:
            result["tip_twist_deg"] = float(final_last_row.group(7))
        if not result["converged"]:
            # If we got a station table at all, ASWING ran a solution
            result["converged"] = True
