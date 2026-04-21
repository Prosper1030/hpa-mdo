# Birdman Upstream Concept Design Line Design

## Purpose

This design defines a new upstream line for `hpa-mdo`:

`Birdman mission + environment + pilot power`
-> `from-scratch aircraft concept generation`
-> `airfoil zoning + CST templates + polar database`
-> `launch / turn / trim / stall envelope evaluation`
-> `3~5 ranked aircraft concepts`
-> existing `inverse design -> jig shape -> CFRP / discrete layup` mainline

The purpose of this line is not to replace the current realizability mainline.
Its job is to answer an earlier question:

- Existing mainline: can this candidate be realized?
- New upstream line: what aircraft concept should be pursued in the first place?

The first version is Birdman-specific, not a generic textbook aircraft sizing tool.

## Why This Is A Separate Line

The current repo already has a strong downstream line for:

- outer-loop aero screening
- inverse design
- jig / loaded shape handling
- CFRP / discrete layup realization

What it does not yet have is a clean upstream line that starts from:

- Birdman rules
- mission objective
- launch and turn requirements
- human power limits
- concept-level geometry choices

This new line exists so the repo can support from-scratch aircraft concept design without overloading the downstream structural workflow.

## First-Version Goal

The first version should produce `3~5` candidate aircraft concepts for the Birdman human-powered propeller class, each with:

- large-geometry definition
- airfoil zoning recommendation
- simplified prop-aware performance coupling
- launch feasibility result
- turn-capability result
- trim / stall / local safety result
- explicit risks and reasons it did not rank higher

The first version must be useful for concept selection, not final certification.

## Birdman Mission And Rule Assumptions

The first version is based on the 2026 Birdman human-powered propeller mission:

- target mission distance: `42.195 km`
- route requires south and north route completion
- route switching requires pylon turns near the platform
- final success requires reaching the designated landing/water touchdown zone
- flight height is constrained near the platform reference height
- launch is from a `10 m` platform with `10 m` run-up

This means the concept line cannot optimize only for straight-line cruise.
It must preserve enough capability for:

- launch from the platform
- low-altitude flight
- pylon-turn-capable operation
- hazard-avoidance margin

## First-Version Design Assumptions

### Environment

- temperature: `33 C`
- relative humidity: `80%`
- air properties should be computed from these conditions, not standard atmosphere defaults

### Mission / Power

- target distance: `42.195 km`
- power is an input
- speed is a solved result
- rider power model should reuse the current mission-line fake power-duration contract anchored at `300 W @ 30 min` until measured data is available

### Mass

- pilot mass: `60 kg`
- baseline aircraft mass assumption: `40 kg`
- gross-mass sweep: `95 / 100 / 105 kg`

The first version should not pretend aircraft mass is already known exactly. The sweep exists to avoid overfitting the concept to a single optimistic number.

### Configuration Family

- conventional configuration only
- one main wing
- aft tail
- left-right symmetric aircraft
- straight wing planform
- linear taper
- linear twist
- no aileron in MVP
- single propeller
- fixed `2-blade` baseline for MVP
- propeller located between main wing and tail as the baseline configuration

The architecture should still leave room to expand blade-count options later.

### Assembly / Transport

- wing segment length must satisfy `1.0 m <= segment length <= 3.0 m`
- segmentation is both a transport constraint and an assembly-practicality constraint

This prevents mathematically attractive but operationally unbuildable over-segmentation.

## Recommended Architecture

### Main Flow

`mission_definition`
-> `geometry_concept_generator`
-> `AVL / quasi-3D concept analysis`
-> `zone_requirement_builder`
-> `Julia(XFoil.jl) airfoil worker`
-> `polar_db + CST template outputs`
-> `prop-aware performance coupling`
-> `launch / turn / trim / stall envelope evaluation`
-> `concept_ranker`
-> `mainline_handoff`

### Guiding Principle

Python remains the orchestrator for the first version.
Julia is introduced as a dedicated airfoil-analysis worker, not as a replacement for the repo's main orchestration layer.

This matches the current repo pattern:

- Python owns campaigns, artifacts, summaries, and ranking
- specialist solvers can be external tools with stable machine-readable contracts

## Module Boundaries

### `mission_definition`

Responsible for:

- Birdman route and rule assumptions
- environment inputs
- rider power model
- gross-mass sweep
- launch / turn / touchdown mission settings

Output:

- one canonical mission/config contract consumed by all later modules

### `geometry_concept_generator`

Responsible for:

- generating candidate values for span, area, aspect ratio, taper, twist, tail size, CG range, and segmentation plan
- enforcing configuration-family limits
- enforcing `1.0 m <= segment <= 3.0 m`

Output:

- candidate concept geometry definitions before detailed airfoil assignment

### `zone_requirement_builder`

Responsible for:

- using AVL or a compatible quasi-3D method to estimate spanwise requirements
- converting concept-level loading into zone-level targets

Output per zone:

- representative `Re`
- representative `cl`
- trim-related moment constraints
- thickness minimums
- stall-margin targets

### `airfoil_worker_bridge`

Responsible for:

- calling `Julia + XFoil.jl`
- managing seed airfoils
- applying bounded CST deformation
- caching polar runs
- handling solver failures without crashing the outer loop
- generating clean and dirty polar variants

This module must treat Julia as a reusable worker toolchain. The first version should not require rewriting the repo into Julia.

### `prop_coupling_model`

Responsible for:

- preserving propeller design space in the architecture
- coupling concept performance to a simplified prop model

MVP behavior:

- do not perform full propeller inner-loop optimization
- do model propeller assumptions as part of the aircraft concept
- do not reduce propeller effects to one fixed universal efficiency constant

Minimum prop concept variables / metadata:

- diameter assumption
- rpm operating range assumption
- `2-blade` baseline
- prop longitudinal position assumption
- simplified `eta_p(V, P)` or equivalent power/thrust coupling

This keeps the line aerodynamically complete enough for concept work without exploding scope.

### `safety_envelope_evaluator`

Responsible for the first-version flight envelope logic. This is not a full textbook envelope tool. It is a concept-level safety evaluator.

It must include:

- `ground-effect-aware launch gate`
- `15 deg bank` turn gate
- trim gate
- local stall gate
- tip-vs-root safety checks

### `concept_ranker`

Responsible for:

- combining mission success, safety gates, assembly practicality, and performance into an auditable ranking
- selecting `3~5` final concepts

The ranking contract must remain explainable. It must show why each concept ranked where it did.

### `mainline_handoff`

Responsible for turning selected concepts into downstream-ready packages for the existing inverse-design mainline.

## Airfoil Design Contract

The first version should follow the CST-based closed-loop direction, but keep the inner loop bounded.

### Recommended MVP Strategy

- start from seed airfoils
- apply limited CST parameterization
- evaluate with `Julia(XFoil.jl)`
- keep multiple operating points per zone
- preserve structural thickness and trim constraints

### Required Outputs

The canonical output is not just `.dat`.

The formal airfoil outputs must be:

- `CST coefficients`
- zone template metadata
- interpolation / blending rules
- lofting guides for downstream CAD use

`.dat` files are analysis artifacts or interchange files, not the authoritative design representation.

This ensures downstream lofting can use mathematical templates instead of dense point clouds, improving continuity and CAD handoff quality.

## Launch And Turn Gates

### Launch Gate

The launch module must not check only lift-at-release.

It must explicitly include:

- platform launch condition
- low-height-above-water behavior
- ground-effect-aware logic
- risk of abrupt induced-drag / trim / pitch-up changes near the surface

The first version may use a simplified ground-effect-aware model, but it must not ignore the effect architecturally.

### Turn Gate

The first-version turn requirement is a conservative hard requirement:

- low-altitude operation
- fixed available rider power
- `15 deg bank`
- must retain trim feasibility
- must retain stall margin

This is intentionally a turn-capability gate, not yet a full turn-trajectory simulator.

## First-Version Scope

### In Scope

- Birdman-specific upstream concept design
- concept-level geometry generation
- zone-based airfoil design with CST templates
- `Julia(XFoil.jl)` airfoil worker integration
- simplified prop-aware coupling
- launch gate with ground-effect handling
- `15 deg bank` turn gate
- trim / local stall / root-tip safety evaluation
- `3~5` ranked final concepts
- downstream handoff package for the existing mainline

### Out Of Scope

- no canard / tailless / highly unconventional aircraft families
- no full propeller blade geometry optimizer in MVP
- no full CFD launch or turn solver
- no full `V-n` envelope implementation
- no full multidisciplinary optimization over geometry, prop, airfoil, and structure at once
- no two-way aeroelastic closure as a requirement for MVP
- no unrestricted prop-position search

## Core Artifacts

The first version should create a stable artifact set, not ad hoc files per script.

### Required Artifacts

- `concept_config.yaml`
  - mission, environment, power model, weight sweep, geometry-family limits, prop assumptions, launch/turn gate settings
- `stations.csv`
  - station-level wing geometry and zoning contract
- `zone_requirements.json`
  - per-zone aerodynamic and structural requirements
- `airfoil_templates.json`
  - CST coefficients, seed references, geometric limits, zone metadata
- `lofting_guides.json`
  - spanwise interpolation and continuity rules for CAD / downstream handoff
- `polar_db/`
  - clean and dirty polar cache produced through the Julia worker
- `prop_assumption.json`
  - simplified prop model assumptions used by the selected concept
- `concept_summary.json`
  - mission, launch, turn, trim, stall, assembly, and ranking outputs
- `selected_concepts/`
  - final `3~5` concept handoff bundles

## Required Final Outputs

Each selected concept should include:

- geometry summary
- airfoil zoning summary
- CST parameter outputs
- lofting guidance
- prop model assumptions
- mission-fit metrics
- launch result
- turn result
- trim result
- local stall / tip-root safety result
- assembly / segmentation summary
- key risks
- why it did not rank higher

This is critical. The first version should not output only a winning scalar. It must produce human-auditable concept packages.

## Integration With Existing Mainline

This line should remain upstream and separate from the current inverse-design implementation.

Recommended pattern:

- new line owns concept design
- existing line owns realizability and structural follow-through
- handoff happens through explicit artifacts, not by hiding concept logic inside downstream structural scripts

Recommended repo relationship:

`new upstream concept-design line`
selects concept packages
-> `handoff package`
-> existing `inverse design -> jig -> CFRP` mainline

This preserves the current verified downstream workflow while opening a much more appropriate front-end for Birdman from-scratch design.

## Success Criteria For The First Version

The first version is successful if it can:

- take one Birdman-style mission/config input
- generate concept candidates inside the allowed family
- evaluate them under the required mass sweep
- generate zone-level airfoil requirements
- call a Julia-based airfoil worker and build a polar database
- evaluate launch, turn, trim, and local stall safety
- produce `3~5` ranked concept packages
- hand off the selected concepts to the current mainline without redefining downstream ownership

## Recommended First Cut

The best first cut is:

- Python orchestrator
- Julia/XFoil.jl worker
- seed airfoils plus bounded CST deformation
- simplified prop coupling
- Birdman-rule-aware mission and safety gates
- concept ranking plus explicit handoff artifacts

This is the smallest version that still behaves like a true concept-design line instead of another narrow downstream helper.
