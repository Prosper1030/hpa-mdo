# HPA-MDO: Human-Powered Aircraft Multidisciplinary Design Optimization Framework

A Python framework for structural optimization of human-powered aircraft wing spars, with integrated aerodynamic load parsing, finite element analysis, and CAE export. Built for the **Black Cat 004** -- a 33 m wingspan HPA.

---

## Architecture Overview

```
                        configs/blackcat_004.yaml
                                 |
                                 v
                    +------------------------+
                    |   Config (Pydantic)     |
                    |   core/config.py        |
                    +------------------------+
                         |            |
                         v            v
              +----------------+  +------------------+
              | VSPAero Parser |  | Aircraft Builder  |
              | aero/vsp_aero  |  | core/aircraft     |
              +----------------+  +------------------+
                         |            |
                         v            v
                    +------------------------+
                    |   Load Mapper           |
                    |   aero/load_mapper      |
                    +------------------------+
                                 |
                                 v
                    +------------------------+
                    |  OpenMDAO FEM Solver    |
                    |  (6-DOF Timoshenko)     |
                    |  structure/oas_struct   |
                    +------------------------+
                                 |
                                 v
                    +------------------------+
                    |  Spar Optimizer         |
                    |  structure/optimizer    |
                    +------------------------+
                         |            |
                         v            v
              +----------------+  +------------------+
              | ANSYS Export   |  | Results / Plots   |
              | APDL/CSV/BDF  |  | utils/visual       |
              +----------------+  +------------------+
                                 |
              +-----------+------+------+-----------+
              |           |             |           |
              v           v             v           v
          FastAPI     MCP Server    Surrogate    stdout
         api/server  api/mcp_server  DB csv    val_weight
```

---

## Features

- **OpenMDAO-based 6-DOF Timoshenko beam FEM** (SpatialBeam formulation) with analytic derivatives
- **Segmented carbon-fiber tube design** -- 11 tubes at 3.0 m each, half-span modeled as 6 segments [1.5, 3.0, 3.0, 3.0, 3.0, 3.0] m
- **Dual-spar equivalent stiffness** -- main spar at 25% chord, rear spar at 70% chord, combined via parallel axis theorem for EI and GJ
- **Lift wire support** -- vertical displacement constraint at wire attachment joint positions
- **VSPAero integration** -- parses `.lod` (spanwise loads) and `.polar` (integrated coefficients) output files
- **ANSYS APDL / Workbench CSV / NASTRAN BDF export** -- auto-generated input files for independent FEA verification
- **FastAPI + MCP server** for AI agent integration (Claude Code, remote batch jobs, web dashboards)
- **Surrogate model training data collection** -- writes design evaluations to CSV for ML model training
- **Separate safety factors** -- `aerodynamic_load_factor` for loads, `material_safety_factor` for allowable stress (never conflated)
- **External material database** -- all properties loaded from `data/materials.yaml` by key

---

## Installation

Requires Python 3.10+. Compatible with Mac (Apple Silicon / Intel) and Windows.

```bash
git clone https://github.com/Prosper1030/hpa-mdo.git
cd hpa-mdo
pip install -e ".[all]"
```

Optional dependency groups:

| Group | Packages | Purpose |
|-------|----------|---------|
| `oas` | openaerostruct, openmdao | FEM solver (required for optimization) |
| `api` | fastapi, uvicorn | REST API server |
| `mcp` | mcp | Model Context Protocol for AI agents |
| `dev` | pytest, pytest-cov, ruff | Development and testing |
| `all` | All of the above | Full installation |

Install a subset with `pip install -e ".[oas,api]"`.

---

## Quick Start

Run the full optimization pipeline on the Black Cat 004 configuration:

```bash
python examples/blackcat_004_optimize.py
```

Or using the configuration flag pattern:

```bash
python scripts/run_optimization.py --config configs/blackcat_004.yaml
```

This will:
1. Load the YAML configuration and build the aircraft model
2. Parse VSPAero aerodynamic data (`.lod` file)
3. Map aero loads onto structural beam nodes, re-dimensionalizing with actual flight conditions
4. Optimize segment wall thicknesses to minimize spar mass
5. Export results to ANSYS formats and save plots

The last line of stdout is always `val_weight: <float>` (the optimized full-span spar mass in kg), which serves as the objective value for upstream AI agent loops.

---

## Project Structure

```
hpa-mdo/
  configs/
    blackcat_004.yaml          # Primary aircraft configuration
  data/
    materials.yaml             # Material property database
  database/
    training_data.csv          # Surrogate model training samples
  examples/
    blackcat_004_optimize.py   # End-to-end optimization example
  output/
    blackcat_004/              # Results, plots, ANSYS exports
  src/hpa_mdo/
    core/
      config.py                # Pydantic schema (mirrors YAML exactly)
      aircraft.py              # Wing geometry, flight condition, airfoil data
      materials.py             # MaterialDB loader (external YAML)
    aero/
      base.py                  # SpanwiseLoad dataclass, AeroParser ABC
      vsp_aero.py              # VSPAero .lod/.polar parser
      xflr5.py                 # XFLR5 parser (alternative)
      load_mapper.py           # Aero-to-structure load interpolation
    structure/
      spar.py                  # TubularSpar geometry builder
      spar_model.py            # Tube section properties, dual-spar math
      oas_structural.py        # OpenMDAO Timoshenko beam components
      optimizer.py             # SparOptimizer (OpenMDAO + scipy fallback)
      ansys_export.py          # APDL, Workbench CSV, NASTRAN BDF writers
    fsi/
      coupling.py              # One-way and two-way FSI coupling
    api/
      server.py                # FastAPI REST endpoints
      mcp_server.py            # MCP server for AI agent tools
    utils/
      visualization.py         # Matplotlib plotting utilities
  tests/
  pyproject.toml               # Build config, dependencies
```

---

## Configuration

All engineering parameters are defined in `configs/blackcat_004.yaml`. The config is validated at load time by the Pydantic schema in `core/config.py`.

### Key Sections

**`flight`** -- Cruise conditions used for load re-dimensionalization.
```yaml
flight:
  velocity: 6.5        # cruise TAS [m/s]
  air_density: 1.225    # ISA sea level [kg/m^3]
```

**`safety`** -- Separate factors for loads and materials.
```yaml
safety:
  aerodynamic_load_factor: 2.0   # design limit load [G]
  material_safety_factor: 1.5    # knock-down on UTS
```

**`wing`** -- Planform geometry, airfoil definitions, and torsion constraint.
```yaml
wing:
  span: 33.0
  root_chord: 1.39
  tip_chord: 0.47
  max_tip_twist_deg: 2.0   # torsion constraint
```

**`main_spar` / `rear_spar`** -- Segmented tube definitions. The `segments` list defines half-span tube lengths (root to tip). The `material` key references `data/materials.yaml`.
```yaml
main_spar:
  material: "carbon_fiber_hm"
  segments: [1.5, 3.0, 3.0, 3.0, 3.0, 3.0]   # sum = 16.5 m half-span
  min_wall_thickness: 0.8e-3                     # manufacturing lower bound [m]
```

**`lift_wires`** -- Cable attachment positions (must coincide with joint locations).
```yaml
lift_wires:
  attachments:
    - { y: 7.5, fuselage_z: -1.5, label: "wire-1" }
```

**`solver`** -- FEM discretization and optimizer settings.
```yaml
solver:
  n_beam_nodes: 60
  optimizer: "SLSQP"
  fsi_coupling: "one-way"
```

**`io`** -- File paths for VSPAero data, airfoil coordinates, and output directories.

---

## API Usage

### FastAPI REST Server

Launch the server:

```bash
uvicorn hpa_mdo.api.server:app --host 0.0.0.0 --port 8000 --reload
```

Or via the installed entry point:

```bash
hpa-mdo
```

Example endpoints:

```bash
# Health check
curl http://localhost:8000/health

# List materials
curl http://localhost:8000/materials

# Run optimization (POST)
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{"config": {...}, "lod_file_path": "/path/to/file.lod", "aoa_deg": 3.0}'

# Export ANSYS APDL
curl -X POST http://localhost:8000/export/ansys-apdl \
  -H "Content-Type: application/json" \
  -d '{"config": {...}, "lod_file_path": "/path/to/file.lod"}'
```

### MCP Server (for AI Agents)

Add to Claude Code's MCP configuration:

```json
{
  "mcpServers": {
    "hpa-mdo": {
      "command": "python",
      "args": ["-m", "hpa_mdo.api.mcp_server"]
    }
  }
}
```

Available MCP tools:

| Tool | Description |
|------|-------------|
| `list_materials` | List all materials in the database |
| `parse_vspaero` | Parse a `.lod` file and return spanwise load distribution |
| `optimize_spar` | Run full spar optimization from config + aero data |
| `export_ansys` | Optimize and export to APDL, CSV, and/or NASTRAN formats |
| `beam_analysis` | Evaluate a specific design point without optimization |

---

## For AI Agents

The framework is designed for automated optimization loops. Every successful run prints a final line:

```
val_weight: <float>
```

where `<float>` is the optimized full-span spar system mass in kilograms. On solver failure or unphysical results, this value is `99999`. Upstream agents should parse this value as the objective to minimize.

Design variables are the 12 segment wall thicknesses (6 per spar, 2 spars). Constraints are stress ratio (failure_index <= 0), tip twist (<= 2 degrees), and deflection. The optimizer uses a two-phase strategy: differential evolution for global search, then SLSQP for local refinement.

---

## Target Aircraft

**Black Cat 004** is a human-powered aircraft with:

- 33.0 m wingspan
- 96 kg operating weight (40 kg airframe + 56 kg pilot)
- 6.5 m/s cruise speed at sea level
- Clark Y SM root airfoil, FX 76-MP-140 tip airfoil
- Progressive dihedral (0 to 6 degrees)
- Main spar at 25% chord, rear spar at 70% chord
- High-modulus carbon fiber tubes (Toray M46J class, E = 230 GPa)
- Lift wire at 7.5 m span station

---

## License

MIT
