from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path


class GmshRuntimeError(RuntimeError):
    """Raised when the Gmsh Python API cannot be loaded."""


def candidate_gmsh_lib_dirs() -> list[Path]:
    candidates: list[Path] = []

    gmsh_binary = shutil.which("gmsh")
    if gmsh_binary is not None:
        binary_path = Path(gmsh_binary).expanduser().resolve()
        candidates.append(binary_path.parent.parent / "lib")

    candidates.extend(
        [
            Path("/opt/homebrew/opt/gmsh/lib"),
            Path("/opt/homebrew/lib"),
            Path("/usr/local/opt/gmsh/lib"),
        ]
    )

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    return unique_candidates


def load_gmsh():
    try:
        import gmsh  # type: ignore

        return gmsh
    except ImportError:
        pass

    for lib_dir in candidate_gmsh_lib_dirs():
        gmsh_py = lib_dir / "gmsh.py"
        if not gmsh_py.exists():
            continue
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))
        importlib.invalidate_caches()
        try:
            import gmsh  # type: ignore

            return gmsh
        except ImportError:
            continue

    raise GmshRuntimeError(
        "gmsh Python API is not available. Keep Homebrew gmsh installed or expose gmsh.py on PYTHONPATH."
    )
