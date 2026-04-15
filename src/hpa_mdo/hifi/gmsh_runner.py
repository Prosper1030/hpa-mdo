"""Gmsh CLI runner for high-fidelity validation meshes."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from hpa_mdo.core.config import HPAConfig


def find_gmsh(cfg: HPAConfig) -> str | None:
    """Return an absolute Gmsh executable path, or ``None`` when unavailable."""

    gmsh_cfg = cfg.hi_fidelity.gmsh
    if not gmsh_cfg.enabled:
        return None

    configured = gmsh_cfg.binary
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        discovered = shutil.which(str(configured))
        if discovered:
            return str(Path(discovered).resolve())
        return None

    discovered = shutil.which("gmsh")
    if discovered:
        return str(Path(discovered).resolve())
    return None


def mesh_step_to_inp(
    step_path: str | Path,
    out_inp_path: str | Path,
    cfg: HPAConfig,
    *,
    order: int = 1,
) -> Path | None:
    """Mesh a STEP file to CalculiX-compatible ``.inp`` via the Gmsh CLI."""

    gmsh = find_gmsh(cfg)
    if gmsh is None:
        print("INFO: Gmsh disabled or not found; skipping STEP mesh.")
        return None

    step = Path(step_path)
    out = Path(out_inp_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        gmsh,
        str(step),
        "-3",
        "-format",
        "inp",
        "-order",
        str(order),
        "-clmax",
        str(cfg.hi_fidelity.gmsh.mesh_size_m),
        "-o",
        str(out),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"INFO: Gmsh timed out after {exc.timeout}s while meshing {step}.")
        return None
    except OSError as exc:
        print(f"INFO: Gmsh failed to start: {exc}")
        return None

    if result.returncode == 0 and out.exists():
        return out

    stderr = result.stderr.strip() or result.stdout.strip()
    if stderr:
        print(f"INFO: Gmsh mesh failed:\n{stderr}")
    else:
        print(f"INFO: Gmsh mesh failed with return code {result.returncode}.")
    return None
