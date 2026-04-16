"""High-fidelity validation helpers.

These modules intentionally stay outside the main MDO loop.  Missing
external solvers should make standalone validation scripts skip, not fail.
"""

from hpa_mdo.hifi.calculix_runner import (
    find_ccx,
    prepare_buckle_inp,
    prepare_static_inp,
    run_static,
)
from hpa_mdo.hifi.gmsh_runner import find_gmsh, mesh_step_to_inp
from hpa_mdo.hifi.paraview_state import (
    discover_frd_files,
    make_pvpython_script,
)

__all__ = [
    "discover_frd_files",
    "find_ccx",
    "find_gmsh",
    "make_pvpython_script",
    "mesh_step_to_inp",
    "prepare_buckle_inp",
    "prepare_static_inp",
    "run_static",
]
