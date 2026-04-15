"""High-fidelity validation helpers.

These modules intentionally stay outside the main MDO loop.  Missing
external solvers should make standalone validation scripts skip, not fail.
"""

from hpa_mdo.hifi.gmsh_runner import find_gmsh, mesh_step_to_inp

__all__ = ["find_gmsh", "mesh_step_to_inp"]
