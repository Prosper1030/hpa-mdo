# CalculiX Parity Gate

## Purpose

CalculiX is the Mac-local structural cross-check solver for the Phase 14 beam benchmark ladder. It is intended to catch beam-deck bookkeeping and model-form problems early, without turning ANSYS/APDL into a daily execution dependency.

This route is a linear-static parity route first:

- use CalculiX beam decks for B1-B5
- compare internal beam references against external FEM on controlled cases
- treat APDL as the later external confirmation route, not the day-to-day gate

## What This Gate Is

- A local beam-element parity check for Phase 14 benchmark cases
- A solver-discovery path that respects repo config overlay via `load_config(...)`, `find_ccx(cfg)`, and `find_gmsh(cfg)`
- A report-first validation layer that writes benchmark decks, runs `ccx_2.23` when available, and summarizes internal-vs-FEM errors under `output/phase14_dual_beam_calibration/`

## What This Gate Is Not

- Not a replacement for the later ANSYS/APDL external check
- Not a nonlinear large-deflection route
- Not a STEP -> Gmsh shell-mesh validation route for B1-B5
- Not an implementation of ASWING, aeroelastic trim, flutter, or beam-wire nonlinear behavior
- Not permission to edit `dual_beam_production` physics equations, hard gates, or aerodynamic ranking

## Scope Rules

- Use linear static CalculiX only
- Do not enable `NLGEOM` in this parity gate
- Do not use `WIRE_MAIN_TRUSS` as the first wire benchmark mode
- First wire rung is the APDL-style vertical wire surrogate: main-wire-node `UZ = 0`
- If a wire node is also a rib-link node, the CalculiX deck may reverse the `*EQUATION` dependency on `UZ` to satisfy MPC hierarchy rules while preserving the same kinematic intent
- Rib transfer is rigid-link / equal-DOF parity first; finite-stiffness rib surrogates belong to a later rung

## Solver Policy

- CalculiX is the Mac-local, fast-turnaround structural cross-check solver
- ANSYS/APDL remains the final external check when a benchmark is mature enough to deserve it
- Gmsh / shell / solid routes remain separate higher-fidelity inspections; they are not the first-line truth source for B1-B5 beam parity

## ASWING Boundary

The ASWING manual and repo research notes are allowed as conceptual references only:

- large-deflection beam behavior
- flexible-joint ideas
- future beam-wire / aeroelastic direction
- coordinate-system caution

They are not part of this MVP implementation. No ASWING-like solver behavior should be added here.

## Current Phase 14 MVP Readout

Current Mac-local evidence from the CalculiX beam parity runner:

- B1 tip-load and uniform-load cantilevers pass closed-form and internal-vs-FEM checks
- B3 dual-beam lift-only parity passes the current 5% displacement target
- B2 tapered cantilever remains a warning case; the present gap points to tapered EI / section interpolation mismatch between the internal reference and the CalculiX B32R pipe route
- B4 vertical-wire and B5 torque variants are usable as displacement spot-checks, but support-reaction bookkeeping is not yet trustworthy enough to call them final validation truth

## Practical Use

Run:

```bash
./.venv/bin/python -m pytest tests/test_phase14_calculix_beam_export.py tests/test_phase14_calculix_beam_benchmarks.py -q
./.venv/bin/python scripts/phase14_calculix_beam_benchmarks.py --config configs/blackcat_004.yaml --output-dir output/phase14_dual_beam_calibration/round2_benchmarks
```

Expected artifacts:

- `output/phase14_dual_beam_calibration/round2_benchmarks/*.inp`
- `output/phase14_dual_beam_calibration/round2_benchmarks/*.frd`
- `output/phase14_dual_beam_calibration/round2_benchmarks/*.dat`
- `output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv`
- `output/phase14_dual_beam_calibration/comparison_summary.md`

## Engineering Interpretation

- Passing B1 means the local CalculiX beam deck, units, section syntax, and cantilever bookkeeping are sane
- Passing B3 means the explicit front/rear beam split plus rigid-link parity deck is directionally credible
- B4 and B5 should still be treated as warning-level evidence until wire support reactions and torque ownership contract are cleaner
- Do not use this route to justify production calibration factors or to silently reweight hard constraints
