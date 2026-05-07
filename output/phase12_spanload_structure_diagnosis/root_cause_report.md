# Root Cause Report

## Clear Diagnosis

The 6-7 deg states are heavy because the canonical model is being asked to realize a low total loaded beam-line Z with the current span, wire setup, catalog tubes, spanload, and target z(y) scaling. At 6 deg the selected design jumps to thick 8 mm walls and about 77 kg of tube, while at about 8.9 deg it can allow about 1.64 m equivalent elastic recovery and drops to about 11.6 kg.

This points to a coupled shape/spanload/stiffness recovery problem, not an aerodynamic power problem.

## Cause Ranking

1. Most likely root cause: requested loaded z(y) is too globally low/stiff for this beam/wire/jig model. The model cannot allow the natural elastic recovery it wants, so it buys stiffness with huge tube wall thickness.
2. Second likely root cause: the current AVL spanload is not absurdly outboard, but it is still structurally consequential. A deliberately more-inboard synthetic target reduced 6 deg tube mass from 77.0 kg to 14.7 kg, although it still failed mass and clearance.
3. Third likely root cause: beam-line vs aerodynamic z definition is still only a proxy. The 6-7 deg guideline belongs to loaded aero surface/quarter-chord geometry; our sweep controls main/rear structural beam lines.
4. Fourth likely root cause: structural layout/wire geometry/catalog discretization. The current catalog creates large mass jumps, and the single available wire geometry may not exploit lift-wire relief enough at low loaded Z.

## Fourier And AVL

- Current 6 deg tube mass: 77.01360725359352 kg.
- More-inboard synthetic spanload 6 deg tube mass: 14.702920907067146 kg.
- Fourier+AVL can reduce structural burden by generating lower root-bending families, but it cannot fix an incompatible loaded z(y)/wire/jig contract by itself.
- The current AVL spanload is already slightly inboard of ellipse; therefore the answer is not 'move load outward like a pretty bent wing'. Moving load outward increases root bending.

## Birdman House-Style Hypothesis

Yes, Birdman House-style outboard bending suggests we should change the requested loaded z(y) shape, not just scalar tip z. The simple exponent-only test did not change the 77 kg result, so the right experiment is a control-station loaded-shape family with wire attach/pretension/layout options, then AVL rerun on the realizable loaded shape.

## Immediate Next Experiment

Run a two-dimensional structure search at 6-7 deg aerodynamic effective dihedral: target tip z plus loaded-shape exponent/control-station z(y), with wire attach/pretension options. Keep AVL spanload fixed first, then repeat for one more-inboard Fourier target. Success criterion: <11.5 kg tube mass, >=20 mm jig clearance, acceptable wire tension, and AVL loaded-shape power penalty quantified.

## What Not To Do Yet

- Do not rerun broad CST/NSGA.
- Do not promote 4.25 m / 13.9 deg as production just because it passes mass.
- Do not treat Fourier e_theory as ranking truth without AVL realization.
- Do not change hard gates until beam-line-to-aero-surface z mapping and real loaded-shape AVL recheck are closed.
