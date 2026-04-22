# Birdman Concept Safety Gates Wiring Design

## Purpose

This design defines the first non-stubbed safety-evaluation pass for the Birdman upstream concept line.

The goal is not to build a full mission simulator.
The goal is to replace the current placeholder concept summary fields:

- `launch`
- `turn`
- `trim`
- `local_stall`

with actual concept-level judgments derived from the current YAML input surface and existing concept bundle data.

## Why This Exists

The current concept pipeline already supports:

- Birdman mission/environment config
- concept geometry generation
- zone requirement generation
- airfoil worker wiring
- concept bundle output
- OpenVSP handoff preview

But the safety block in `concept_summary.json` still reports `stubbed_ok`.

That means the pipeline can generate concepts, but it still cannot honestly answer the practical Birdman questions:

- can this candidate leave the platform safely?
- can it survive the required `15 deg` turn gate?
- is trim margin positive or negative at the selected operating point?
- is some local wing section, especially outboard, already too close to stall?

This task closes that gap without trying to solve the entire mission line at once.

## Scope

### In Scope

- wire `launch` summary to the existing `evaluate_launch_gate()` logic
- wire `turn` summary to the existing `evaluate_turn_gate()` logic
- compute a simple `trim` feasibility result from launch/turn inputs and configured trim-margin thresholds
- compute a simple `local_stall` result from the current spanwise/zone requirement data
- make the resulting summaries depend on:
  - `launch.release_speed_mps`
  - `launch.min_trim_margin_deg`
  - `launch.min_stall_margin`
  - `launch.use_ground_effect`
  - `turn.required_bank_angle_deg`
  - current concept geometry
  - current zone/station `cl_target`
- update tests so these summaries are no longer allowed to stay as unconditional stub placeholders

### Out of Scope

- full mission power-duration coupling
- full race-route simulation
- full turn-radius / pylon-geometry modeling
- high-fidelity launch dynamics
- slipstream-resolved aerodynamics
- full stability-and-control model

## Recommended Approach

### Option A: Full Mission Solver Now

Build a full chain:

`pilot power -> thrust -> speed solution -> launch / turn / trim / stall envelope`

Pros:

- more physically complete

Cons:

- scope is much too large for this wave
- hard to debug when several approximations fail at once
- risks freezing the upstream concept line before it becomes practically usable

### Option B: Safety Gates From Current State Variables

Use the current concept data already available in the pipeline:

- concept geometry
- configured release speed
- configured bank angle
- zone/station `cl_target`
- simple `cl_max` estimate from current zone data contract

Then compute:

- launch pass/fail
- turn pass/fail
- trim feasible/not feasible
- local stall margin pass/fail

Pros:

- smallest useful step
- directly answers current Birdman concept questions
- keeps the safety layer inspectable and debuggable

Cons:

- still a coarse approximation
- not yet a full mission-level answer

### Recommendation

Use Option B.

This gives the concept line a real engineering filter without pretending the repo already has a full mission solver.

## Design

### 1. Launch Gate Contract

The launch gate should be evaluated from the release state, not from the pilot spin-up phase.

Interpretation:

- `launch.mode = restrained_pre_spin` means the propeller may already be at operating RPM before release
- the launch gate begins at the instant the aircraft is released

Inputs:

- `launch.platform_height_m`
- `launch.release_speed_mps`
- `launch.use_ground_effect`
- `launch.min_trim_margin_deg`
- concept span
- concept-level required `CL`
- concept-level available `CL`

First-version behavior:

- use the configured release speed as the launch-state speed
- derive launch `CL_required` from gross weight, release speed, density, and wing area
- derive launch `CL_available` from the highest current spanwise `cl_target` plus a conservative margin proxy
- evaluate trim feasibility from a simple positive-margin threshold

Output:

- `launch.status`
- `launch.feasible`
- `launch.reason`
- `launch.adjusted_cl_required`
- `launch.cl_available`
- `launch.trim_margin_deg`
- `launch.release_speed_mps`
- `launch.ground_effect_applied`

### 2. Turn Gate Contract

The turn gate should answer only:

`can this concept survive a conservative 15 deg banked Birdman turn without losing its stall margin or trim feasibility?`

Inputs:

- `turn.required_bank_angle_deg`
- concept operating speed
- representative wing `cl_level`
- representative `cl_max`
- trim feasible flag

First-version behavior:

- use the configured bank angle directly
- evaluate the coordinated-turn load increase with:
  - `n = 1 / cos(phi)`
- use that to compute increased required `CL`
- compare the result against the concept’s representative `cl_max`

Output:

- `turn.status`
- `turn.feasible`
- `turn.reason`
- `turn.required_cl`
- `turn.stall_margin`
- `turn.bank_angle_deg`

### 3. Trim Contract

The first-version trim result is intentionally simple.

It should not claim full aircraft trim analysis.
It should answer:

`does this concept still have positive trim margin under the simplified launch/turn operating point assumptions?`

Inputs:

- configured `launch.min_trim_margin_deg`
- representative local/zone `cm_target`
- simple moment proxy derived from current zone data

First-version behavior:

- compute a conservative trim-margin proxy
- classify as feasible if the proxy exceeds the configured minimum threshold

Output:

- `trim.status`
- `trim.feasible`
- `trim.reason`
- `trim.margin_deg`
- `trim.required_margin_deg`

### 4. Local Stall Contract

This is the most important first-version safety output for concept ranking.

It should answer:

- which station or zone is closest to stall?
- is the concept safely root-first or at least not tip-critical?

Inputs:

- current spanwise/zone `cl_target`
- a simple `cl_max` estimate per point
- station `y`

First-version behavior:

- compute local stall margin per point:
  - `stall_margin = cl_max - cl_target`
- identify the minimum margin station
- identify whether the limiting station is near the tip
- classify the concept as failed if the minimum margin is below `launch.min_stall_margin`

Output:

- `local_stall.status`
- `local_stall.feasible`
- `local_stall.reason`
- `local_stall.min_margin`
- `local_stall.min_margin_station_y_m`
- `local_stall.tip_critical`

## Pipeline Changes

The pipeline should stop hardcoding:

- `launch = stubbed_ok`
- `turn = stubbed_ok`
- `trim = stubbed_ok`
- `local_stall = stubbed_ok`

Instead it should:

1. derive representative concept-level safety inputs from current stations and zone requirements
2. call the safety evaluators
3. serialize the computed summaries into each candidate bundle
4. surface these same summaries into the top-level concept summary output

## Testing Strategy

### Unit Tests

- launch gate responds to configured release speed and trim margin thresholds
- turn gate responds to configured bank angle and stall margin thresholds
- local stall flags tip-critical concepts
- trim status flips when the configured margin threshold is tightened

### Pipeline Tests

- custom YAML settings change concept summary safety outputs
- concept bundle summaries no longer contain unconditional `stubbed_ok`
- smoke output contains numeric launch/turn/trim/local-stall fields

## Expected Outcome

After this task, the upstream concept line should still be coarse, but it should become honest.

It will no longer merely say:

- `launch: stubbed_ok`
- `turn: stubbed_ok`

It will instead say, in a simplified but engineering-meaningful way:

- this concept can or cannot leave the platform safely
- this concept can or cannot pass the conservative Birdman turn gate
- this concept does or does not retain trim margin
- this concept is or is not locally stall-critical near the tip
