# Recommended Structure Trust Policy

## Immediate Policy

Do not use the Phase 12 z-state mass cliff as a production hard gate. Keep aerodynamic ranking and hard gates unchanged.

## Model Use By Purpose

| purpose | recommended model | trust level | policy |
|---|---|---|---|
| fast bending/mass sanity and regression | `equivalent_beam` / tube beam | high for its own assumptions because APDL parity is strong | Use as an anchored check and trend sanity tool, not as current jig truth. |
| concept-stage HPA shape screening | concept `jig_shape_gate` | warning only | Use only to flag suspicious deflection/dihedral regimes. |
| loaded-Z and jig trade studies | canonical `scripts/direct_dual_beam_inverse_design.py` using `dual_beam_production` | current best mainline, but spot-check grade | Use for shortlist generation and diagnostics; require branch-continuity checks around any cliff. |
| final spar sizing | dual-beam/inverse jig plus external ANSYS/CalculiX or test benchmark | not complete yet | Do not sign off until apples-to-apples validation is done. |
| discrete layup realization | discrete layup postprocess after continuous sizing | manufacturing screening | Use after the structural branch is stable; do not use as proof of final composite strength. |

## What To Validate Next

1. Export the two cliff-neighbor cases, `target_main_tip_z=2.000 m` and `2.025 m`, with their selected tube recipes and identical load ownership to an external ANSYS/CalculiX comparison.
2. Validate the explicit wire/tension-only reaction and support partition for the same pair; the branch jump also changes wire tension from about 256.2 N to 2772.5 N.
3. Validate inverse-jig clearance: compare target, jig, and loaded shape recovery in an external solver for at least one heavy branch and one light branch.
4. Replace the coarse `0/1` MVP grid near cliffs with a local continuous/refined search before making any engineering rejection.
5. Only after branch continuity is fixed, run discrete layup and Tsai-Wu/manufacturing realization on the selected branch.

## Decision Rule For 6-7 Deg

Keep 6-7 deg pending model audit. The current fixed-spanload, fixed-wire, coarse-grid model says 6 deg is not mass-feasible and 7 deg is still above the 11.5 kg tube target, but the discontinuity and load-ownership sensitivity make hard rejection premature.
