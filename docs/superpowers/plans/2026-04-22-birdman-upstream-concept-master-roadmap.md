# Birdman Upstream Concept Design Line Master Roadmap

## Purpose

This roadmap defines the remaining work required to turn the current Birdman upstream concept line from a working MVP skeleton into an engineering-usable closed loop:

`Birdman rules / environment / rider power / mass`
-> `from-scratch geometry concept generation`
-> `spanwise / zone requirements`
-> `bounded CST airfoil deformation`
-> `Julia(XFoil.jl) polar evaluation`
-> `launch / turn / trim / local-stall / ground-effect checks`
-> `simplified prop-aware coupling`
-> `fixed-range best-time mission scoring`
-> `3~5 ranked aircraft concepts`
-> `OpenVSP + downstream mainline handoff`

This document is intentionally larger than the existing task plans.
The older plans define implementation waves.
This roadmap defines the full remaining sequence, why the order matters, and what the next engineering priority should be.

## Current Snapshot

### Already Completed

- dedicated Birdman upstream concept config surface
- geometry-family generation for a constrained Birdman concept family
- segmentation and station contract
- zone requirement builder skeleton
- concept bundle / handoff artifacts
- OpenVSP preview handoff
- first safety-gate wiring for:
  - `launch`
  - `turn`
  - `trim`
  - `local_stall`
- real `Julia + XFoil.jl` worker path
- seed-airfoil based 2D polar evaluation
- `fixed_range_best_time` mission mode for the Birdman `R = 42.195 km` rule:
  finish-capable speeds are ranked by completion time, while concept ranking
  still puts feasibility margin ahead of thin speed gains; non-finishers fall
  back to maximum range for comparison.

### Still Incomplete

- real 2D polar outputs do **not** yet fully drive safety and ranking
- CST exists as a contract and handoff format, but not yet as the active airfoil design inner loop
- `clmax`, `cm`, and `cd` are not yet fully coupled back into concept decisions
- simplified prop coupling is still too weak to meaningfully shape concept ranking
- fixed-range best-time scoring is connected, but the underlying drag / prop /
  rider-endurance calibration is still diagnostic rather than decision-grade
- current safety judgments still lean on coarse proxies
- current concept ranking is not yet trustworthy enough for real design choice

### Practical Interpretation

The current line is no longer a fake skeleton.
It can run, produce artifacts, and call a real airfoil solver.
But it is still closer to a concept-design framework than a concept-design decision engine.

## End-State Definition

This line should be considered "first useful closed loop" only when all of the following are true:

- airfoil candidates are generated through bounded CST deformation, not only fixed seed airfoils
- `Julia/XFoil.jl` returns usable polar data for all active zones and operating points
- `clmax`, `cm`, and `cd` influence:
  - safety gates
  - trim judgment
  - concept ranking
- launch and turn gates respond to actual airfoil capability, not only a proxy headroom model
- simplified prop coupling changes concept ranking in a visible and explainable way
- the final selected concepts can be reviewed in:
  - concept summary artifacts
  - OpenVSP handoff
  - downstream mainline bundle format

## Roadmap Principles

### Principle 1: Close the Feedback Loop Before Expanding the Search Space

Do not widen the geometry or airfoil design space until the current real polar results actually influence concept decisions.

### Principle 2: Keep Python As Orchestrator

Julia remains a specialist worker.
Do not rewrite the concept line into a mixed-orchestrator architecture.

### Principle 3: Preserve Honest Engineering Boundaries

Do not label the result as a full mission solver, CFD tool, or full MDO stack before the corresponding loop is truly closed.

### Principle 4: Keep This Line Separate From The Downstream Mainline

This roadmap is for upstream concept design.
It should not collapse back into the existing inverse-design / jig / CFRP line.

## Phase Map

## Phase 1: Real Polar Feedback Into Safety And Ranking

### Goal

Make the current real `Julia/XFoil.jl` polar outputs materially affect concept evaluation.

### Why This Comes First

Until this phase is done, adding CST optimization mostly optimizes against incomplete downstream logic.
That would create attractive but misleading airfoil results.

### Main Work

- replace current `cl_max_proxy` dependence where possible with airfoil-derived capability
- extract usable representative quantities from polar results:
  - `cd`
  - `cm`
  - near-target `cl`
  - first usable `clmax` proxy from real 2D data
- feed those values into:
  - `launch`
  - `turn`
  - `trim`
  - concept ranking
- make safety summaries explain whether the decision came from:
  - real polar data
  - fallback proxy

### Expected Outputs

- concept summaries that explicitly cite airfoil-driven safety values
- ranking changes when airfoil choice changes
- fewer false positives caused by coarse proxy-only logic

### Exit Criteria

- changing airfoil seeds measurably changes launch / turn / trim / ranking outputs
- concept summaries record which values were airfoil-derived
- no remaining unconditional dependence on the current coarse `cl_max_proxy` for the primary pass/fail decisions

### Main Risks

- XFoil convergence gaps at low Reynolds numbers
- unstable or misleading `clmax` extraction from sparse polar data

## Phase 2: Bounded CST Airfoil Inner Loop

### Goal

Turn the current airfoil flow from:

`fixed seed airfoils -> XFoil.jl`

into:

`seed airfoils -> bounded CST deformation -> XFoil.jl -> zone scoring`

### Why This Comes Second

This is the phase where the line truly starts "designing" airfoils rather than just evaluating fixed seeds.
It should only happen after Phase 1 ensures the returned polar data matters downstream.

### Main Work

- extend `airfoil_cst.py` from contract-only use into active geometry generation
- define bounded CST parameterization:
  - seed-following, not free-form
  - fixed coefficient counts per zone family
  - TE thickness handling
- add geometry validity checks:
  - non-negative thickness
  - no self-intersection
  - bounded curvature / usable leading edge shape
- export `.dat` coordinates from CST candidates for Julia worker input
- score candidates per zone using multipoint requirements

### Expected Outputs

- CST-generated candidate airfoils per zone
- CST coefficients as canonical airfoil artifacts
- `.dat` only as an analysis exchange format

### Exit Criteria

- at least one concept run uses CST-generated airfoils instead of raw seed coordinates
- `airfoil_templates.json` authority shifts from "seed preview" to real CST candidate definitions
- invalid CST candidates fail fast and do not break outer-loop execution

### Main Risks

- too many CST degrees of freedom causing unstable optimization
- low-Re XFoil sensitivity producing noisy candidate ordering

## Phase 3: Multipoint Airfoil Evaluation And 2D-to-3D Coupling

### Goal

Make the airfoil selection logic reflect real Birdman operating conditions rather than one-point matching.

### Main Work

- expand zone operating points:
  - multiple `Re`
  - multiple `cl`
  - clean / dirty transition assumptions
- improve `clmax` estimation logic
- couple 2D outputs back into 3D concept metrics:
  - stall margin
  - trim burden
  - profile drag contribution
- track zone-wise risk:
  - root structural thickness pressure
  - tip stall pressure
  - negative-moment burden on trim

### Expected Outputs

- each zone evaluated on a small operating set rather than a single point
- concept-level summaries that report where the design is fragile
- early Pareto trade-off visibility among:
  - drag
  - moment
  - stall margin
  - thickness

### Exit Criteria

- concept ranking changes when clean/dirty assumptions change
- airfoil zone selection is no longer reducible to one `CL target`
- local stall summaries can reference a zone-specific `clmax` basis

### Main Risks

- too much compute cost if multipoint sweeps are expanded too aggressively
- false confidence from 2D polars if 3D coupling remains too loose

## Phase 4: Simplified Prop-Aware Coupling

### Goal

Make propeller assumptions shape concept performance in a meaningful but bounded way.

### Main Work

- strengthen `propulsion.py` from metadata holder into an actual concept-performance input
- incorporate:
  - prop diameter
  - rpm range
  - blade-count baseline
  - longitudinal placement assumption
  - simplified `eta_p(V, P)` model
- feed prop-aware outputs into:
  - mission score
  - launch reasoning
  - ranking explanations

### Expected Outputs

- ranking that distinguishes aerodynamically good but prop-mismatched concepts
- concept bundles that show prop assumptions as a real design contributor

### Exit Criteria

- changing prop assumptions changes concept score in an explainable way
- propulsion assumptions are visible in concept summaries and not only sidecar metadata

### Main Risks

- overconfidence in simplified prop assumptions
- accidental drift toward a hidden propeller optimizer without enough data

## Phase 5: Concept Ranking And Candidate Explanation Hardening

### Goal

Turn the line from a collection of evaluators into an auditable concept-selection tool.

### Main Work

- redesign ranking explanation fields so the final `3~5` concepts show:
  - why they ranked where they did
  - which gate dominated
  - what main engineering risk remains
- separate:
  - hard fail
  - soft warning
  - rank penalty
- improve candidate diversity so the final top concepts are not near-duplicates

### Expected Outputs

- clearer concept comparison tables
- more useful top-`N` candidate set for discussion and review

### Exit Criteria

- top concepts are not merely clones with different IDs
- every selected concept has a short engineering explanation
- every rejected concept has a visible dominant failure reason

### Main Risks

- hidden ranking weights producing arbitrary-looking outcomes
- too much penalty stacking reducing explainability

## Phase 6: OpenVSP And Downstream Handoff Maturation

### Goal

Make selected concepts reviewable in geometry tools and portable into the realizability mainline.

### Main Work

- improve OpenVSP handoff from preview-level output toward aircraft-level review output
- ensure handoff packages stay centered on:
  - `concept_config.yaml`
  - `stations.csv`
  - `airfoil_templates.json`
  - `lofting_guides.json`
  - `prop_assumption.json`
  - `concept_summary.json`
- verify geometry fields are complete enough for downstream use

### Expected Outputs

- top concepts that can be inspected visually in OpenVSP
- stable bundle contract for later inverse-design handoff

### Exit Criteria

- selected concepts can be opened and inspected without manual geometry patching
- downstream handoff no longer depends on hidden assumptions in the concept pipeline

### Main Risks

- preview geometry looking valid while metadata contracts remain incomplete
- too much VSP-specific logic leaking into the concept generator

## Phase 7: Engineering Sanity Check And Confidence Pass

### Goal

Move from "pipeline works" to "pipeline is worth trusting for first-round concept choice."

### Main Work

- compare clean vs dirty sensitivity
- inspect low-Re reasonableness for chosen airfoils
- challenge launch and turn thresholds from an HPA engineering perspective
- inspect whether tip-stall tendency and trim burden look believable
- document known limitations honestly

### Expected Outputs

- a concept-line review note describing:
  - what is believable
  - what is still weak
  - what should not yet be over-interpreted

### Exit Criteria

- final candidate set survives a first engineering sanity review
- remaining weaknesses are explicit and documented

### Main Risks

- mistaking a passing smoke pipeline for a validated design engine
- using sparse low-Re results as if they were wind-tunnel truth

## Recommended Immediate Next Step

### Do Next

**Phase 1: Real Polar Feedback Into Safety And Ranking**

This is the immediate next step because it closes the most important open loop with the highest value-to-effort ratio.

### Do Not Do First

- do not widen the geometry concept family first
- do not start full propeller optimization first
- do not start free-form CST optimization first
- do not start route-level mission simulation first

Those all multiply complexity before the current real airfoil results actually influence decisions.

## Execution Order Summary

1. `real polar -> safety / ranking`
2. `bounded CST inner loop`
3. `multipoint and 2D-to-3D coupling`
4. `simplified prop-aware coupling`
5. `ranking / candidate diversity hardening`
6. `OpenVSP + downstream handoff maturation`
7. `engineering sanity check`

## Rough Time Expectation

If this line is worked continuously and remains isolated from unrelated tracks:

- first truly airfoil-driven concept results: about `1~2 weeks`
- first useful closed-loop concept-selection version: about `3~5 weeks`
- first engineering-confidence review version: about `4~8 weeks`

These are engineering estimates, not promises.
The biggest uncertainty is not Python wiring.
It is low-Re airfoil reliability, `clmax` extraction stability, and how much of the current concept ranking changes once real polar feedback is fully enforced.

## Success Definition For The Whole Roadmap

This roadmap succeeds when the repo can do all of the following in one reproducible upstream run:

- generate Birdman-specific aircraft concepts from mission inputs
- assign zone-wise airfoil candidates through bounded CST design
- evaluate those candidates with `Julia/XFoil.jl`
- rank concepts using airfoil-informed launch / turn / trim / stall logic
- preserve propeller assumptions as real concept variables
- export `3~5` reviewable candidate concepts for OpenVSP and downstream mainline use

Until then, the line should still be described as an evolving upstream concept-design pipeline, not a complete HPA design optimizer.
