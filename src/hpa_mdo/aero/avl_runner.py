"""Drive the AVL binary to emit stability-derivative (``.st``) output.

The existing sweep campaign scripts (``scripts/dihedral_sweep_campaign.py``,
``scripts/multi_wire_sweep_campaign.py``) each grew their own inline
subprocess calls.  For the controls-interface exporter (M13) we need a
thin, reusable runner that just:

1. Writes a temporary command script.
2. Pipes it to ``avl`` with a wall-clock timeout.
3. Collects the resulting ``.st`` path plus the stdout log.
4. Returns a plain dict (never raises) so the caller can produce a
   partial report even when AVL crashes.

The command sequence follows the canonical trim→ST recipe documented
in AVL's manual:

    load <geom.avl>
    mass <mass.mass>        # optional
    oper
      m
        v <velocity>
        d <density>
      <trim command>        # either 'a a <alpha>' or 'a c <cl>'
      x
      st <stub>.st
    quit
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class AvlRunResult:
    """Outcome of a single ``run_avl_derivatives`` call."""

    st_path: Optional[Path]
    run_path: Optional[Path]
    stdout_log_path: Optional[Path]
    returncode: int
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "st_path": None if self.st_path is None else str(self.st_path),
            "run_path": None if self.run_path is None else str(self.run_path),
            "stdout_log_path": (
                None if self.stdout_log_path is None else str(self.stdout_log_path)
            ),
            "returncode": int(self.returncode),
            "error": self.error,
        }


def _resolve_binary(binary: Optional[str]) -> Optional[Path]:
    """Return an absolute path to the AVL binary, or ``None`` if not found."""
    if binary:
        candidate = Path(binary).expanduser()
        if candidate.is_absolute() and candidate.exists():
            return candidate
        which_hit = shutil.which(str(candidate))
        if which_hit:
            return Path(which_hit)
        if candidate.exists():
            return candidate.resolve()
    fallback = shutil.which("avl")
    return Path(fallback) if fallback else None


def _build_command_text(
    *,
    avl_filename: str,
    mass_filename: Optional[str],
    alpha_deg: Optional[float],
    cl_target: Optional[float],
    velocity: Optional[float],
    density: Optional[float],
    st_filename: str,
) -> str:
    lines = ["plop", "g", ""]
    lines.append(f"load {avl_filename}")
    if mass_filename is not None:
        lines.append(f"mass {mass_filename}")
        # ``MSET 0`` forces the CG/inertia in the loaded .mass to be
        # applied to all run cases.  Without it AVL keeps its own
        # per-run values from the .avl file.
        lines.append("mset")
        lines.append("0")
    lines.append("oper")

    # Environment block — only open if we actually override something.
    if velocity is not None or density is not None:
        lines.append("m")
        if velocity is not None:
            lines.append(f"v {float(velocity):.9f}")
        if density is not None:
            lines.append(f"d {float(density):.9f}")
        lines.append("")  # exit env menu

    # Trim constraint.
    if cl_target is not None:
        # Constraint 1 = alpha-by-CL (standard AVL default slot).
        lines.append("c1")
        lines.append(f"c {float(cl_target):.9f}")
        lines.append("")
    elif alpha_deg is not None:
        lines.append("a")
        lines.append("a")
        lines.append(f"{float(alpha_deg):.9f}")
    # Else: run case uses whatever was set in the .avl.

    lines.append("x")
    lines.append("st")
    lines.append(st_filename)
    lines.append("")  # exit OPER
    lines.append("")  # extra blank for safety
    lines.append("quit")
    lines.append("")
    return "\n".join(lines)


def run_avl_derivatives(
    *,
    avl_path: Path,
    out_dir: Path,
    avl_binary: Optional[str] = None,
    mass_path: Optional[Path] = None,
    alpha_deg: Optional[float] = None,
    cl_target: Optional[float] = None,
    velocity: Optional[float] = None,
    density: Optional[float] = None,
    timeout_s: float = 120.0,
    stem: str = "controls_trim",
) -> AvlRunResult:
    """Run AVL once, trim to the requested condition, and emit a ``.st`` file.

    Parameters
    ----------
    avl_path:
        The geometry ``.avl`` to load.  Will be copied into ``out_dir``
        so AVL (which works on filenames relative to ``cwd``) can see it.
    out_dir:
        Working directory for the run.  Created if missing.
    avl_binary:
        Optional explicit binary path; falls back to ``shutil.which("avl")``.
    mass_path:
        Optional ``.mass`` file.  If provided it is copied into ``out_dir``
        and loaded via the ``MASS`` / ``MSET 0`` commands.
    alpha_deg, cl_target:
        Mutually exclusive trim constraints.  ``cl_target`` takes
        precedence when both are given.
    velocity, density:
        Environment overrides, both optional.
    timeout_s:
        Wall-clock timeout for the AVL subprocess.

    Returns
    -------
    AvlRunResult
        Never raises.  On failure the ``error`` field contains a short
        string and ``returncode`` is non-zero.
    """

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    binary = _resolve_binary(avl_binary)
    if binary is None:
        return AvlRunResult(
            st_path=None,
            run_path=None,
            stdout_log_path=None,
            returncode=127,
            error="avl_binary_not_found",
        )

    avl_path = Path(avl_path)
    if not avl_path.exists():
        return AvlRunResult(
            st_path=None,
            run_path=None,
            stdout_log_path=None,
            returncode=2,
            error=f"avl_geometry_missing:{avl_path}",
        )

    # Stage inputs inside the run directory so AVL's cwd-relative paths work.
    staged_avl = out_dir / avl_path.name
    if staged_avl.resolve() != avl_path.resolve():
        staged_avl.write_bytes(avl_path.read_bytes())

    staged_mass: Optional[Path] = None
    if mass_path is not None:
        mass_path = Path(mass_path)
        if not mass_path.exists():
            return AvlRunResult(
                st_path=None,
                run_path=None,
                stdout_log_path=None,
                returncode=2,
                error=f"avl_mass_missing:{mass_path}",
            )
        staged_mass = out_dir / mass_path.name
        if staged_mass.resolve() != mass_path.resolve():
            staged_mass.write_bytes(mass_path.read_bytes())

    st_file = out_dir / f"{stem}.st"
    if st_file.exists():
        st_file.unlink()
    run_file = out_dir / f"{stem}.run"
    stdout_log = out_dir / f"{stem}_stdout.log"

    command_text = _build_command_text(
        avl_filename=staged_avl.name,
        mass_filename=None if staged_mass is None else staged_mass.name,
        alpha_deg=alpha_deg,
        cl_target=cl_target,
        velocity=velocity,
        density=density,
        st_filename=st_file.name,
    )
    run_file.write_text(command_text, encoding="utf-8")

    try:
        proc = subprocess.run(
            [str(binary)],
            input=command_text,
            text=True,
            capture_output=True,
            cwd=out_dir,
            timeout=float(timeout_s),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_log.write_text(
            "AVL timed out after %.1fs\n" % float(timeout_s)
            + (exc.stdout or "" if isinstance(exc.stdout, str) else ""),
            encoding="utf-8",
        )
        return AvlRunResult(
            st_path=None,
            run_path=run_file,
            stdout_log_path=stdout_log,
            returncode=124,
            error="avl_timeout",
        )
    except OSError as exc:
        return AvlRunResult(
            st_path=None,
            run_path=run_file,
            stdout_log_path=None,
            returncode=1,
            error=f"avl_spawn_failed:{exc}",
        )

    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")

    if proc.returncode != 0 and not st_file.exists():
        return AvlRunResult(
            st_path=None,
            run_path=run_file,
            stdout_log_path=stdout_log,
            returncode=int(proc.returncode),
            error="avl_nonzero_exit",
        )

    if not st_file.exists():
        return AvlRunResult(
            st_path=None,
            run_path=run_file,
            stdout_log_path=stdout_log,
            returncode=int(proc.returncode),
            error="st_file_not_produced",
        )

    return AvlRunResult(
        st_path=st_file,
        run_path=run_file,
        stdout_log_path=stdout_log,
        returncode=int(proc.returncode),
        error=None,
    )


__all__ = ["AvlRunResult", "run_avl_derivatives"]
