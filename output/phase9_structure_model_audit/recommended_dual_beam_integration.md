# Recommended Dual-Beam Integration

## Recommendation

Replace the Phase 9 structure/jig proxy with a production-baseline dual-beam validation sidecar before promoting the smooth Tier2 baseline to a structural baseline. Do not change the aerodynamic ranking or production hard gates until the new sidecar has been run and reviewed.

The correct next implementation is an adapter from the smooth production aerodynamic package into the existing dual-beam mainline model.

## Proposed Implementation Step

Create a validation script or module with a narrow contract, for example:

- `scripts/validate_smooth_tier2_dual_beam_structure.py`

Its job should be:

1. Read the smooth production baseline geometry package:
   - `section_table.csv`
   - AVL file
   - geometry manifest
   - AVL spanload / strip-force output
   - airfoil assignment
2. Build a structural station model:
   - main spar node coordinates
   - rear spar node coordinates
   - spar offsets from chord and section geometry
   - target loaded shape from the existing loaded z/twist convention
3. Map aerodynamic loads:
   - lift per span from AVL
   - torque per span from section moment data where available
   - fallback torque policy clearly marked if AVL/airfoil Cm mapping is incomplete
4. Select structural recipe inputs:
   - main/rear spar radii
   - wall thickness distribution
   - material properties
   - rib/link mode
   - wire attachment/anchor layout
   - cable diameter/material/allowable tension
   - wire reference and unstretched lengths or pretension policy
5. Instantiate `DualBeamMainlineModel`.
6. Run:
   - `run_dual_beam_mainline_kernel(mode=AnalysisModeName.DUAL_BEAM_PRODUCTION)`
   - `wire_bc=WireBCMode.WIRE_MAIN_TRUSS` if explicit wire anchors and lengths are available
   - an explicit `link_mode`, preferably the current production link/rib mode
7. Run inverse jig recovery:
   - `build_frozen_load_inverse_design_from_mainline()`
   - `predict_loaded_shape()` forward refresh check
8. Emit a replacement audit table:
   - tip deflection from solved dual-beam state
   - loaded-shape main z max/RMS error
   - loaded-shape twist max/RMS error
   - unloaded jig node coordinates
   - jig ground clearance min/margin
   - maximum prebend
   - maximum curvature
   - wire tensions and margins
   - main/rear spar stress utilization
   - buckling index if available
   - spar tube mass full
   - total structural mass full
   - failure modes separated into stiffness, strength, wire, mass, and jig-shape causes

## Minimum Inputs Needed

The adapter should fail closed unless these inputs are present or explicitly defaulted with a `proxy_input` flag:

- smooth production section stations with y, z, chord, twist
- main and rear spar chordwise positions
- vertical spar separation or actual main/rear node z offsets
- spanwise structural discretization
- main/rear tube dimensions or recipe variables
- material database keys and modulus/allowables
- AVL spanload at trimmed CL
- section Cm or torque source
- root BC mode
- wire attachment stations and anchor coordinates
- wire cable area, material, allowable tension
- wire unstretched/reference length or pretension definition
- link/rib mode
- jig clearance floor and manufacturing limits

## Suggested Output Location

Write the replacement sidecar here:

- `output/final_candidate_validation/smooth_tier2_production_baseline/dual_beam_structure_validation/`

Suggested files:

- `dual_beam_structure_summary.md`
- `dual_beam_structure_summary.csv`
- `dual_beam_jig_shape_nodes.csv`
- `dual_beam_loaded_shape_recovery.csv`
- `dual_beam_wire_tension.csv`
- `dual_beam_spar_utilization.csv`
- `dual_beam_mass_breakdown.csv`
- `proxy_vs_dual_beam_comparison.csv`

## Engineering Review Gate Before Trusting Results

Before replacing the proxy in reports, check these engineering sanity items:

- total integrated AVL lift matches mission gross weight within tolerance
- root bending from dual-beam reactions is consistent with `integral(y * L'(y) dy)`
- wire tensions are tensile and below allowable with a meaningful margin
- wire pretension or unstretched length assumptions are physically stated
- loaded-shape recovery matches the target at root, mid, and tip control stations
- unloaded jig shape does not violate ground clearance or unrealistic prebend/curvature
- spar mass is separated into carbon tubes, joints/fittings, ribs, wires, and margins
- strength and stiffness failures are reported separately
- material modulus and allowables come from the material database, not a single hard-coded `120e9 Pa`

## Keep The Proxy As A Warning Layer

The existing proxy should not be deleted. Keep it as a fast warning sidecar because it is cheap and catches obvious load-shape/mass problems early. Rename or label it consistently as:

- `structure_proxy_warning`
- `not_structure_grade`
- `concept_stage_only`

The production-facing structural statement should come from the dual-beam / wire-truss / inverse-jig validation, not from the Phase 9 scalar proxy.
