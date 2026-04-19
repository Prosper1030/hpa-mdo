# Mission Objective Line Design

## Purpose

This design defines a new upstream design line for `hpa-mdo`:

`mission objective`
-> `mission-ranked candidate`
-> existing `AVL-first -> inverse design -> jig shape -> CFRP/discrete layup` mainline

The purpose of this line is not to replace the current realizability mainline. Its job is to answer a different question earlier in the workflow:

- Existing mainline: can this candidate be realized?
- New mission line: which candidate is worth pursuing for the mission objective?

For the first version, the mission objective line must support:

- `max_range`
- `min_power`

The first version uses a fake rider power-duration model anchored at:

- `300 W @ 30 min`

This is a temporary engineering placeholder that establishes the contract and data flow before real pilot data is available.

## Why This Is A Separate Line

The repo already has a strong realizability-oriented mainline:

- lightweight aero screening
- inverse design
- jig / loaded shape outputs
- CFRP / discrete layup realization

What it does not yet have is a clean upstream layer that chooses candidates based on mission intent instead of only structural feasibility or single-point aerodynamic signals.

This new line exists to make mission intent explicit and machine-readable, so later work can connect:

- real rider power-duration data
- zone airfoil / twist redesign
- transport / segmentation constraints

without repeatedly redefining what the candidate ranking is trying to optimize.

## First-Version Goal

The first version should make mission objective part of candidate ranking.

It should not attempt to be a full mission simulator. The intended outcome is:

- each outer-loop candidate receives mission metrics
- winner selection can switch between `max_range` and `min_power`
- the same mission layer can later consume real rider data without redesigning the contract

## First-Version Scope

### In Scope

- Add an explicit mission-objective evaluator ahead of downstream realizability checks
- Support `max_range` and `min_power`
- Use a fake monotone `P(t)` model generated from `300 W @ 30 min`
- Sweep a small range of cruise speeds per candidate
- Emit mission metrics into summaries / winner evidence

### Out Of Scope

- no wind model
- no climb, launch, acceleration, or turn-energy model
- no full mission segmentation
- no transport constraint integration into mission score
- no direct CST/XFOIL inner loop yet
- no full aeroelastic loop closure

## Operating Assumptions

The first version assumes:

- steady level cruise
- fixed altitude
- no wind
- distance is approximated by `range = V * t_available`
- candidate comparison is still shortlist-oriented, not final flight-truth certification

These assumptions are intentionally narrow so the repo can gain a usable mission-oriented ranking signal without overcommitting to an immature mission model.

## Recommended Architecture

### Placement

The new layer sits between outer-loop aero candidate generation and the current inverse-design / CFRP realizability line.

Recommended flow:

`candidate geometry`
-> `aero evaluation over small speed sweep`
-> `mission evaluator`
-> `mission-ranked candidate`
-> `inverse design`
-> `jig / loaded / CFRP / discrete layup`

### Main Principle

The mission evaluator must not redefine the structural truth or replace the current realizability gates.

Instead:

- mission line decides what is worth pushing downstream
- realizability line decides whether it can actually be built and flown

This keeps the new line additive instead of disruptive.

## Objective Modes

### `max_range`

For each candidate and each sampled cruise speed:

1. estimate required cruise power `P_required(V)`
2. map that power into available duration `t_available`
3. compute `range(V) = V * t_available(V)`
4. keep the best speed and best range

Candidate comparison uses the best achievable range from the scanned speed window.

### `min_power`

For each candidate:

1. estimate `P_required(V)` over the same speed window
2. keep the minimum required power and the corresponding speed

Candidate comparison uses the minimum required cruise power.

### Why Speed Sweep Is Required

Without a speed sweep, `max_range` would collapse toward `min_power` because both would be evaluated at a single fixed cruise speed.

A small speed sweep is therefore mandatory even in the MVP, otherwise the new objective-mode switch would be mostly fake.

## Fake Rider Power-Duration Model

### Contract

The first version should expose a rider model abstraction with:

- model type
- anchor assumptions
- generated power-duration curve metadata

### Recommended Fake Model

Use a simple monotone curve anchored at `300 W @ 30 min`:

`P_fake(t_min) = clip(300 * (30 / t_min)^0.15, 180, 450)`

Properties:

- exactly matches `300 W @ 30 min`
- allows higher short-duration power
- decays smoothly for longer durations
- is easy to replace later with imported real data

This model is not meant to claim physiological truth. It is a placeholder contract generator.

### Derived Usage

The evaluator needs the inverse query:

- given `P_required`, estimate `t_available`

So implementation should treat the fake rider model as a reusable object that can answer both:

- `power_at_duration(t)`
- `duration_at_power(P)`

This interface should remain stable when real rider data replaces the fake model later.

## Required Inputs

The first version should add a small mission config surface with:

- `objective_mode`
- `speed_sweep_min_mps`
- `speed_sweep_max_mps`
- `speed_sweep_points`
- rider model type
- rider anchor power
- rider anchor duration

Recommended defaults:

- `objective_mode = max_range`
- `speed_sweep_min_mps = 6.0`
- `speed_sweep_max_mps = 10.0`
- `speed_sweep_points = 9`
- rider anchor = `300 W @ 30 min`

## Required Outputs

Each candidate should emit mission fields alongside existing score / gate outputs:

- `mission_objective_mode`
- `mission_feasible`
- `best_range_m`
- `best_range_speed_mps`
- `best_endurance_s`
- `min_power_w`
- `min_power_speed_mps`
- `mission_score`
- `mission_score_reason`
- `pilot_power_model`
- `pilot_power_anchor`
- `speed_sweep_window_mps`

These fields should appear in:

- machine-readable summary JSON
- winner evidence
- campaign / feasibility report tables

The key requirement is that mission scoring must be auditable, not hidden inside a derived scalar.

## Scoring Contract

The mission evaluator should produce a mission-specific scalar, but the scalar must remain secondary to explicit fields.

Recommended interpretation:

- `max_range`: larger range is better, so store a score that is monotone with “more negative is better” or convert explicitly during ranking
- `min_power`: smaller power is better

The reporting contract must always show the underlying physical values, not only the normalized score.

## Integration With Existing Ranking

The safest first integration is:

- keep current realizability / gate outputs
- add mission metrics
- let the top-level ranking switch choose whether mission score or existing candidate score is primary

This avoids breaking the existing structural-selection workflow while still making mission intent operational.

Recommended priority order for first version:

1. mission objective score
2. gate / reject status
3. existing realizability score as tie-break

This should be documented explicitly so users know whether a winner was chosen for mission value or for structural conservatism.

## Future Interfaces

### Real Rider Data

The fake rider model is only the first backend for the rider-power contract.

Later versions should support:

- imported power-duration tables
- fitted rider models
- multiple rider profiles

The rest of the mission evaluator should not need redesign when that happens.

### Airfoil Redesign Line

This mission line is the intended upstream selector for the later airfoil redesign work:

`spanwise loads`
-> `zone requirements`
-> `CST/XFOIL`
-> `mission-ranked candidate`
-> `inverse design`

That means the mission objective contract should stay geometry-agnostic and candidate-oriented, not hard-coded to the current fixed-airfoil setup.

### Transport / Segment Constraints

Transport-driven segmentation is important, but it should not be part of the first mission score.

Recommended later role:

- design constraint
- geometry / structure feasibility constraint
- manufacturing / handoff constraint

not:

- first-version mission objective term

This separation keeps mission intent, human power limits, and transport feasibility from being mixed into one opaque number too early.

## Risks

### Risk 1: Fake precision

If the fake `P(t)` is presented like real flight-truth data, users may overtrust the resulting range numbers.

Mitigation:

- label the rider model as `fake_anchor_curve`
- surface the anchor in every summary
- treat results as comparative candidate ranking evidence, not final performance truth

### Risk 2: Objective drift

If mission score is mixed with existing structural score without a clear precedence rule, users will not know what the winner actually optimized.

Mitigation:

- explicit `objective_mode`
- explicit `mission_score_reason`
- explicit winner evidence text

### Risk 3: Scope explosion

It will be tempting to immediately add wind, launch, climb, and transport constraints.

Mitigation:

- lock MVP to steady cruise only
- keep follow-on extensions as later interfaces, not hidden MVP work

## MVP Success Criteria

The first version is successful if:

- users can switch between `max_range` and `min_power`
- each candidate is evaluated over a small speed sweep
- the fake `300 W @ 30 min` rider model is generated automatically
- outputs clearly show mission metrics and objective mode
- downstream realizability flow remains intact

## Recommendation

Implement this as a dedicated mission-objective layer, not as a small hidden tweak to current candidate scoring.

That structure costs a little more up front, but it creates the right foundation for the next waves:

- real rider data import
- zone airfoil / twist redesign
- transport / segment constraint integration

This is the cleanest way to open a new design line without breaking the current mainline contract.
