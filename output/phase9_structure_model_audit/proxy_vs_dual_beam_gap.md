# Proxy vs Dual-Beam Gap

## Classification

The Phase 9 and smooth production baseline structure/jig result is:

- **concept proxy**
- **warning only**
- **not structure-grade**
- **not valid for final spar sizing**

It should not be used as a go/no-go structural sizing result. It is valid as an engineering alarm that says: "the smooth aerodynamic baseline probably needs serious structure/jig work, and the current mass target is not supported by this simple stiffness proxy."

## What The Proxy Does

The current reported structure result uses:

- AVL strip-force spanload
- half-wing lift integral
- root bending proxy: `integral(y * L'(y) dy)`
- tip-deflection load-shape proxy: `integral(y^2 * L'(y) dy)`
- single aggregate per-wing EI
- cantilever uniform-load tip-deflection formula
- scalar lift-wire relief fraction
- scalar unloaded tip estimate: `loaded_tip_z - tip_deflection`
- catalog tube EI/mass proxy with constant tube size across the full span

The proxy does not know the real spar load path. It treats two vertically separated tubes as one aggregate bending stiffness and does not solve main/rear spar deformation, twist, reaction sharing, or wire equilibrium.

## What The Real Dual-Beam Path Can Do

The real path exists and is much closer to the aircraft structure problem:

- `DualBeamMainlineModel` carries main/rear beam nodes, spar offsets, spar section properties, lift, torque, gravity, wire nodes, wire anchor points, wire areas, wire allowable tensions, reference lengths, and unstretched lengths.
- `run_dual_beam_mainline_kernel()` builds load split, constraints, displacements, reactions, recovery metrics, smooth aggregation, optimizer metrics, and feasibility.
- `_evaluate_explicit_wire_truss_support()` solves a nonlinear explicit wire truss support where axial compression is clipped to zero, so it is tension-only.
- `build_frozen_load_inverse_design_from_mainline()` backs out the unloaded jig shape from the target loaded shape and solved dual-beam displacement field.
- `predict_loaded_shape()` re-adds solved displacements to the jig shape to check loaded-shape recovery.

## Gap Matrix

| Capability | Current Phase 9 result | Real dual-beam path |
|---|---|---|
| Main/rear spar separation | Aggregate EI only | Explicit main and rear beam nodes |
| Spanwise stiffness variation | No, except scalar taper correction | Yes, through segment radii/thickness/properties |
| Aerodynamic lift | AVL strip-force integral | Nodal load input via load split |
| Aerodynamic torque | No | Yes, `torque_per_span_nmpm` |
| Root boundary conditions | Implicit cantilever root | Explicit root BC modes |
| Wire support | Prescribed scalar relief fraction | Explicit wire constraints/truss support |
| Tension-only wire | No | Yes in `WIRE_MAIN_TRUSS` branch |
| Wire pretension | No | Possible through reference/unstretched length inputs, but must be intentionally configured |
| Jig shape | Scalar tip subtraction | Nodewise inverse jig shape |
| Loaded-shape recovery | No | `predict_loaded_shape()` |
| Stress/strength | No | Structural response/recovery metrics |
| Buckling | No | Equivalent/optimizer-facing gates where available |
| Mass | Carbon tube only | Spar tube and total structural mass fields |
| Manufacturing clearance | Scalar warning only | Ground clearance, prebend, curvature checks |

## Why Phase 9 Did Not Use The Real Dual-Beam Module

Phase 9 was written as an aerodynamic production/smooth-planform sidecar. Its available geometry state is:

- section table
- AVL geometry
- VSP export
- AVL spanload
- airfoil zone assignment

That is enough for aero rechecks and spanload proxies, but not enough to instantiate `DualBeamMainlineModel` correctly.

Missing inputs for the real dual-beam path include:

- main spar and rear spar node positions in the production geometry coordinate system
- spar x/z offsets relative to each section and the aerodynamic reference line
- spanwise main/rear tube radii and wall thickness distributions
- material properties by spar segment, not one global modulus
- joint, fitting, wire, and rib mass models for this candidate
- main/rear load split policy for lift and aerodynamic torque
- pitching moment or torque distribution mapped from airfoil/AVL work points
- root boundary condition selection for this validation case
- wire attachment stations, fuselage/kingpost anchor points, cable areas, material, allowable tension
- wire reference lengths / unstretched lengths / pretension policy
- link mode: joint-only, dense rigid links, or finite ribs
- target loaded-shape control stations and tolerances for this smooth production geometry
- jig clearance floor, maximum prebend, and curvature limits

The smooth baseline validation reused Phase 9 helper functions intentionally, so it inherited the proxy rather than entering `scripts/direct_dual_beam_inverse_design.py`.

## Engineering Read

The proxy result is still directionally important. A `2.286 m` scalar deflection estimate against a `1.051 m` loaded tip z means the current aerodynamic shape cannot be called production-structure-realistic from this report alone. The negative unloaded tip estimate is a red flag, but not a final failure, because a real wire-trussed dual-beam inverse jig shape may change the deformation distribution substantially.

The `32.959 kg` tube mass is also a red flag, not a final spar mass. It is saying that if the current crude EI target were met using constant full-span catalog tubes with two tubes per half-wing, the tube-only mass would already exceed the current `11.7534 kg` spar tube mass target by about `21.206 kg`. A tapered custom layup, higher modulus material, different wire geometry, or different spar separation could reduce that, but the current proxy cannot prove it.
