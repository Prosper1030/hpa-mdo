# Dual-Beam Module Inventory

## Existing Real Modules

- `src/hpa_mdo/structure/dual_beam_mainline/types.py`: owns `DualBeamMainlineModel`, `AnalysisModeName.DUAL_BEAM_PRODUCTION`, `WireBCMode.WIRE_MAIN_TRUSS`, result dataclasses, recovery fields, and feasibility summaries.
- `src/hpa_mdo/structure/dual_beam_mainline/api.py`: `run_dual_beam_mainline_kernel()` builds load split, constraints, displacements, reactions, structural recovery, smooth aggregation, optimizer metrics, and feasibility.
- `src/hpa_mdo/structure/dual_beam_mainline/solver.py`: `solve_dual_beam_state()` includes the explicit wire-truss nonlinear branch; `_evaluate_explicit_wire_truss_support()` clips compression to zero with `tension_n = max(axial_force, 0)`.
- `src/hpa_mdo/structure/dual_beam_mainline/builder.py`: the config-driven builder can convert configured aircraft/optimizer outputs into a `DualBeamMainlineModel`, including pretension-derived unstretched wire lengths.
- `src/hpa_mdo/structure/inverse_design.py`: `build_frozen_load_inverse_design_from_mainline()` and `predict_loaded_shape()` recover unloaded jig shape and verify loaded-shape closure.
- `scripts/direct_dual_beam_inverse_design.py`: currently callable production workflow using the real kernel and inverse-jig recovery.

## Required Inputs

- front/main and rear spar node coordinates
- spanwise main/rear tube radius and wall distributions
- material E/G/density/allowables
- distributed lift per span and torque per span
- root BC, link/rib mode, and wire BC
- wire attach nodes, anchor coordinates, cable area/material/allowable tension
- wire reference and unstretched lengths; pretension enters through unstretched length
- target loaded shape and jig clearance/manufacturing limits

## Phase 10 Adapter Assumptions

- main spar at `0.25c`; rear spar at `0.70c`
- loaded main spar z from the production section table
- loaded rear spar z from loaded z plus relative twist from the root
- AVL `concept_spanwise.fs` supplies `L'(y)` and `Cm`; torque is approximated as `q*c^2*Cm` about the 25% chord main spar
- one Dyneema SK75 wire at nominal `y=7.5 m`, nearest structural node, anchor `(x_attach, 0, -1.5)`
- wire pretension `0.0 N` because the current baseline config does not define installed pretension
- link mode `joint_only_offset_rigid`

The module is callable from scripts. This Phase 10 script calls it directly rather than using the older config/optimizer builder because the smooth aero package lacks a full structural config.
