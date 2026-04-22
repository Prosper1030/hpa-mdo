# Birdman Bounded CST Inner Loop Design

## Purpose

This design defines how the Birdman upstream concept line should add the missing airfoil-design loop from the user's primary design draft:

`AVL / spanwise loading`
-> `zone requirements`
-> `bounded CST airfoil candidates`
-> `Julia(XFoil.jl)`
-> `zone scoring`
-> `feedback into concept safety / mission / ranking`

The immediate goal is not full MDO or unconstrained airfoil synthesis.
The immediate goal is to make the current Birdman concept line truly start designing airfoils instead of only evaluating fixed seed airfoils.

## Design Intent

The user's reference design document remains the main guide:

- use 3D loading to define local 2D requirements
- use CST as the canonical airfoil parameterization
- use XFOIL-class analysis to evaluate many candidate airfoils
- feed the 2D results back into the 3D concept decision

What this spec adds is the implementation boundary for the next two waves:

- **Phase 1**
  - bounded CST inner loop MVP
  - small candidate family around seed airfoils
  - stable enough to trust the artifact flow and ranking changes
- **Phase 2**
  - larger search / optimizer-based CST exploration
  - more aggressive candidate generation only after Phase 1 is stable

This sequencing is important.
If Phase 2 starts before Phase 1 proves the loop is stable, the line risks producing attractive but misleading low-Re airfoil results.

## Why This Is The Next Priority

The current Birdman concept line already has:

- AVL-backed spanwise loading
- zone requirements
- real Julia/XFoil.jl worker execution
- airfoil-informed safety and mission ranking

But the active airfoil path is still:

`fixed seed airfoils -> Julia/XFoil.jl`

That means the line can evaluate airfoils, but it does not yet generate or improve them.

So the next missing engineering capability is:

`seed airfoil -> bounded CST deformation -> evaluate -> choose better zone candidate`

## Phase Split

## Phase 1: Bounded CST Inner Loop MVP

### Goal

Replace the current seed-only airfoil path with a bounded CST candidate loop that is:

- stable
- auditable
- limited in degrees of freedom
- compatible with the current concept ranking flow

### Phase 1 Flow

For each zone:

`seed airfoil`
-> `fit or assign base CST template`
-> `generate a small bounded candidate family`
-> `export coordinates`
-> `Julia/XFoil.jl`
-> `score candidates against zone requirements`
-> `select one winning CST candidate`
-> `use that candidate in the current concept feedback path`

### Phase 1 Boundaries

Phase 1 must stay conservative:

- no unconstrained free-form airfoil generation
- no large stochastic optimizer yet
- no full cross-zone coupled airfoil optimization yet
- no simultaneous geometry-family explosion

The point is to prove the CST-based airfoil loop works inside the current Birdman concept architecture.

## Phase 2: Expanded CST Search

### Goal

Once Phase 1 is stable, expand the CST loop from a small bounded candidate family into a more complete search.

### Phase 2 Direction

This later phase may include:

- more candidate density per zone
- optimizer-driven CST coefficient search
- clean / dirty multipoint objective expansion
- stronger coupling of drag / moment / stall / thickness penalties

But Phase 2 should only start after Phase 1 proves:

- CST candidates are geometrically valid
- XFoil worker integration is stable
- ranking actually moves in an explainable way

## Airfoil Representation Rules

### Canonical Representation

The canonical airfoil artifact must be:

- `CST coefficients`
- plus metadata describing:
  - seed source
  - trailing-edge thickness
  - geometric bounds
  - zone ownership

`.dat` coordinates are still needed, but only as an exchange format for solver input and debugging.

### CST Authority

`airfoil_templates.json` must evolve from the current seed preview into a true CST-driven artifact.

For each zone, it should ultimately record:

- `template_id`
- `zone_name`
- `seed_name`
- `upper_coefficients`
- `lower_coefficients`
- `te_thickness_m`
- candidate provenance
- selected-score summary

`lofting_guides.json` must continue to use CST coefficient space as the airfoil authority.

## Phase 1 CST Parameterization

Phase 1 should use a bounded, seed-following CST parameterization.

### Base Shape

Each zone starts from one existing seed airfoil:

- inner zones may continue to start from `fx76mp140`
- outer zones may continue to start from `clarkysm`
- this mapping can later become configurable, but Phase 1 can keep the current repo defaults

### Coefficient Count

Phase 1 should keep coefficient counts fixed and modest.

Recommended Phase 1 rule:

- same upper/lower coefficient count across all active zones
- small enough to avoid unstable shapes
- large enough to allow meaningful thickness/camber changes

The exact count is an implementation choice, but it must favor stability over expressiveness.

### Allowed Deformation

Phase 1 candidate generation must be bounded relative to the seed/base CST template.

That means:

- upper coefficients can move only within fixed local bounds
- lower coefficients can move only within fixed local bounds
- trailing-edge thickness remains bounded
- candidate generation must not drift arbitrarily far from the seed

This is a seed-following design loop, not a blank-sheet airfoil synthesis engine.

## Geometry Validity Rules

Every CST-generated candidate must pass fast geometric checks before calling Julia/XFoil.jl.

Phase 1 validity checks must include:

- positive thickness over the chord
- no self-intersection
- usable leading-edge shape
- no degenerate or numerically unstable trailing edge

Invalid candidates must fail fast and receive a penalty or be dropped.
They must not crash the outer concept loop.

## Candidate Generation Strategy

Phase 1 should use deterministic or low-variance bounded candidate generation.

Recommended strategy:

- build one base CST template from the seed airfoil
- generate a small set of nearby coefficient perturbations
- include the unmodified base candidate
- evaluate all valid candidates for that zone

The current line does not need thousands of candidates in Phase 1.
It needs a small, explainable candidate family that proves the loop works.

## XFoil / Julia Worker Contract

The Julia worker stays in the current role:

- Python orchestrates
- Julia/XFoil.jl evaluates coordinates

Phase 1 must not rewrite the worker architecture.

What changes is the source of the coordinates:

- current: direct seed airfoil coordinates
- Phase 1: CST-generated candidate coordinates

Each candidate query must still preserve:

- `template_id`
- `geometry_hash`
- Reynolds number
- CL sample targets
- roughness mode

## Zone Scoring

Phase 1 zone scoring must follow the user's design logic, but in a bounded MVP form.

The score should favor candidates that perform well at the zone's required operating points, not simply candidates with the best peak `L/D`.

Phase 1 scoring should consider:

- near-target drag
- available `clmax` or lower-bound `clmax` signal
- pitching moment burden
- thickness / geometry viability
- solver usability

Phase 1 does not need a sophisticated global optimizer yet, but it does need a real per-zone candidate comparison.

## Feedback Into Concept Decisions

Phase 1 is only complete if the selected CST candidate changes downstream concept behavior.

That means the selected zone candidates must continue to feed:

- launch safety
- turn safety
- trim proxy
- local stall logic
- mission/ranking summaries

This is the real acceptance test:

`CST candidate selection must not stop at the airfoil layer.`

It must alter the concept decision outputs in the same way the real seed-airfoil worker currently does.

## File And Module Responsibilities

### `src/hpa_mdo/concept/airfoil_cst.py`

This file should grow from contract-only support into the active CST geometry module.

Phase 1 responsibilities:

- represent CST templates
- generate coordinates from CST coefficients
- provide bounded candidate generation around a base template
- validate candidate geometry
- produce canonical CST metadata for handoff

### `src/hpa_mdo/concept/pipeline.py`

Phase 1 responsibilities:

- replace the current seed-only template builder with:
  - seed -> base CST -> candidate family -> selected candidate
- send CST-generated coordinates to the worker
- keep the selected CST template in concept artifacts
- keep ranking and summaries backward-compatible where possible

### `src/hpa_mdo/concept/airfoil_worker.py`

No architecture change is required in Phase 1.
It should continue to accept coordinate-driven `PolarQuery` inputs.

### Tests

Phase 1 should be driven by tests that prove:

- CST can generate valid coordinates
- bounded candidate generation respects limits
- invalid candidates are rejected safely
- pipeline can run at least one concept using CST-generated airfoils instead of raw seed coordinates
- `airfoil_templates.json` shifts to CST-driven authority

## Outputs

After Phase 1, each selected concept should still emit:

- `airfoil_templates.json`
- `lofting_guides.json`
- `concept_summary.json`
- optional OpenVSP handoff artifacts

But `airfoil_templates.json` must now represent selected CST candidates instead of only seed snapshots.

## Success Criteria

Phase 1 is successful when all of the following are true:

- at least one concept run uses CST-generated candidate coordinates
- solver runs succeed through the existing Julia/XFoil.jl worker path
- invalid CST candidates do not break the concept loop
- concept summaries still build cleanly
- selected concepts carry CST-based airfoil template data
- downstream safety or mission outputs change in a traceable way when CST candidates differ

## Non-Goals

This wave does not attempt to complete the entire user draft at once.

Phase 1 explicitly does **not** include:

- unconstrained CST search
- thousands of candidates per zone
- full optimizer-driven global airfoil design
- full multipoint clean/dirty expansion
- final structural thickness closure
- full 2D/3D coupled MDO

Those belong to later waves, especially the user's requested Phase 2 after the bounded Phase 1 path is proven.
