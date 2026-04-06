# HPA-MDO AI Development Rules

## Iron Laws (NEVER violate)

1. ALL engineering parameters MUST come from `configs/*.yaml` -- NEVER hardcode physics constants (velocities, densities, safety factors, material properties, geometry dimensions).
2. ALWAYS read config.yaml BEFORE changing solver code. Understand the current parameter values and schema before modifying any module.
3. The structural solver MUST use OpenMDAO architecture -- no standalone scipy beam solvers. The OpenMDAO problem lives in `structure/oas_structural.py`; scipy is only used as a fallback optimization driver wrapped around the OpenMDAO model.
4. Safety factors MUST be separated: `aerodynamic_load_factor` for loads (applied in load mapping), `material_safety_factor` for allowable stress (applied when computing failure index) -- NEVER conflate them into a single factor.
5. Materials MUST be loaded from `data/materials.yaml` by key via `MaterialDB` -- no inline material definitions, no hardcoded E/G/density/strength values anywhere in Python code.
6. External aero loads from VSPAero MUST use actual flight conditions (V=config.flight.velocity, rho=config.flight.air_density) for re-dimensionalization -- NEVER use VSPAero reference conditions directly, as VSPAero may have been run at a different Vinf/rho than the real cruise state.
7. On ANY solver crash or unphysical result, print `val_weight: 99999` and exit gracefully -- NEVER let the process abort with an unhandled exception. The `val_weight` output protocol is consumed by upstream AI agent loops.

## Architecture Rules

- Config schema lives in `core/config.py` (Pydantic BaseModel) -- it mirrors the YAML structure exactly. Any new config field must be added to both the YAML and the Pydantic model.
- Segment wall thicknesses are the design variables: 6 per spar x 2 spars = 12 DVs for the dual-spar configuration. The segments list in config defines half-span tube lengths [1.5, 3.0, 3.0, 3.0, 3.0, 3.0] m.
- The FEM uses global DOFs: [ux, uy, uz, theta_x, theta_y, theta_z] per node -- torsion about the span axis is DOF 4 (theta_y for Y-span beam).
- Dual-spar equivalent stiffness: EI computed from parallel axis theorem (individual tube EI + A*d^2 for each spar), GJ from individual tubes plus warping coupling term. The math lives in `structure/spar_model.py`.
- Joint mass penalty is added to the objective function (total_mass_full_kg), NOT injected into the structural mass distribution along the beam. Joint count is derived from cumsum of segment lengths.
- Lift wire support = vertical displacement constraint (uz = 0) at the wire attachment joint position. Wire attachment y-coordinates must coincide with joint positions defined by segment boundaries.
- The optimizer uses a two-phase strategy: (1) differential evolution for global search, (2) SLSQP for local refinement. OpenMDAO's built-in driver is tried first in "auto" mode; scipy fallback is the robust path.

## File Conventions

- Python 3.10+ compatible (per pyproject.toml requires-python).
- Use `from __future__ import annotations` in all modules.
- Use `from typing import Optional, List` for type annotations.
- All file paths are read from `config.io` -- never hardcoded. Use `pathlib.Path` everywhere.
- Cross-platform: use `pathlib.Path`, avoid platform-specific path separators. The team uses both macOS and Windows.
- Line length limit: 100 characters (enforced by ruff).

## Code Organization

- `core/` -- Configuration, aircraft model, material database. No solver logic here.
- `aero/` -- Aerodynamic parsers (VSPAero, XFLR5) and load mapping. Output is always a `SpanwiseLoad` dataclass or a mapped loads dict.
- `structure/` -- FEM components, spar geometry, optimizer, and CAE export. The OpenMDAO problem is assembled in `oas_structural.py`.
- `fsi/` -- Fluid-structure interaction coupling (one-way and two-way Gauss-Seidel).
- `api/` -- FastAPI REST server and MCP server. These are thin wrappers around the core pipeline.
- `utils/` -- Visualization and helper functions.

## Testing and Validation

- After ANY structural code change, run: `python examples/blackcat_004_optimize.py`
- Check these acceptance criteria:
  - `failure_index <= 0` (stress constraint satisfied)
  - `twist_max_deg <= 2.0` (torsion constraint satisfied)
  - `total_mass_full_kg` is physically reasonable: 15-50 kg for full span spar system
  - `tip_deflection_m` is positive and less than half-span (no sign errors)
- The last output line MUST be `val_weight: <float>` -- this is the machine-readable objective value.
- If adding a new constraint or design variable, verify that OpenMDAO partial derivatives are correct by running `check_partials()` on the affected component.

## Load Mapping Protocol

- VSPAero outputs non-dimensional coefficients (Cl, Cd, Cm) at its own reference conditions.
- The `LoadMapper.map_loads()` function re-dimensionalizes using `actual_velocity` and `actual_density` from config, producing physical force-per-unit-span [N/m] at the real cruise state.
- The `aerodynamic_load_factor` is applied as a multiplicative scale factor during load mapping (not in the FEM solver).
- Aero-to-structure interpolation uses cubic spline by default. The structural mesh (60 nodes) is finer than the aero mesh.

## ANSYS Export

- APDL export uses BEAM188 elements (Timoshenko beam) with CTUBE cross-sections.
- Workbench CSV provides geometry and loads for External Data import.
- NASTRAN BDF uses CBAR elements with PBARL TUBE sections.
- All three formats represent the same half-span model with fixed root boundary condition.
- Export is for independent verification only -- the optimization uses the internal OpenMDAO FEM, not ANSYS.
