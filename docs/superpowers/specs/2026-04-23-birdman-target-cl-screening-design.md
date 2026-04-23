# Birdman Target-CL Screening Design

## Purpose

This design upgrades the Birdman upstream concept line from:

`full alpha sweep for every zone candidate`

to a dual-track airfoil-analysis flow:

`Target-CL screening for all candidates`
-> `full alpha sweep only for finalists`

The goal is not to change the aerodynamic architecture.
The goal is to cut the brute-force screening cost at the real bottleneck:

- viscous XFoil operating-point count
- repeated full alpha sweeps on candidates that never reach the finals

## Design Intent

The main architecture remains:

`AVL spanwise loads`
-> `zone requirements`
-> `bounded CST candidate family`
-> `Julia/XFoil.jl`
-> `safety / mission / ranking`

What changes is the solver fidelity policy.

Instead of treating every candidate as if it deserves a full polar, the line should:

- use a cheap, target-driven operating-point solve during screening
- reserve full polar generation for the few concepts that survive screening

This keeps the current Birdman concept line aligned with the user’s primary design draft while making the brute-force engine meaningfully more scalable.

## Why This Is The Next Priority

The current line already has:

- physical cache identity
- query deduplication
- persistent Julia workers
- multi-worker parallel execution
- cheap CST prescreen

Those changes reduced runtime substantially, but they do not change the dominant cost:

- `XFoil viscous alpha sweep`

So the next performance wave must attack the solver workload itself, not the surrounding orchestration.

## Core Decision

The worker should not depend on a hidden or unstable native `CL mode`.

The currently available Xfoil.jl public path in this environment is clearly alpha-based:

- `solve_alpha(alpha, re; ...)`
- `alpha_sweep(...)`

Therefore the low-risk design is:

- implement `Target-CL` solving in the Julia worker
- using `solve_alpha` plus a bracket / secant loop
- with a conservative fallback to `mini alpha sweep`

This keeps the inversion logic explicit and auditable.

## Dual-Track Flow

## Stage 1: Screening

All zone candidates use a `screening_target_cl` fidelity.

For each candidate, the worker should solve only the operating points needed near the requested lift coefficient:

- `CL_target`
- optionally `CL_target ± delta` when the zone scoring needs a small local slope or safety proxy

The exact point count is an implementation choice, but the screening path should stay in the range of:

- `1 to 3` operating points per candidate

The screening path must not run a full polar by default.

## Stage 2: Finalists

Only the top `L` concepts from the screening pass should be reevaluated with `full_alpha_sweep`.

Recommended Phase 1 default:

- `L = 3`

The finalist pass should:

- rerun the selected zone airfoils for the finalist concepts
- regenerate full polar-derived quantities
- update the finalist concepts’ airfoil feedback, safety summaries, and ranking inputs

The rest of the screened concepts remain screening-only.

## Worker Contract Changes

The query contract must explicitly encode solver fidelity.

`PolarQuery` should gain:

- `analysis_mode`
  - `screening_target_cl`
  - `full_alpha_sweep`
- `analysis_stage`
  - `screening`
  - `finalist`

Optional mode-specific parameters may also be added if needed, such as:

- target-CL bracket limits
- mini-sweep alpha window
- screening delta-CL values

The result payload must echo:

- `analysis_mode`
- `analysis_stage`
- any summary fields needed to distinguish:
  - target-CL screening result
  - full polar result

## Cache Separation

Screening results and full polars must not share the same physical cache entry.

That means the physical cache identity must include:

- airfoil geometry hash
- Reynolds number
- roughness mode
- requested CL samples or equivalent target set
- `analysis_mode`
- any mode-specific fidelity knobs that change the numerical result

This keeps:

- `screening_target_cl`
- `full_alpha_sweep`

in separate cache namespaces even when they use the same geometry.

## Target-CL Solver Strategy

The target-CL screening path should be conservative and explicit.

Recommended solve order:

1. choose an initial alpha bracket
2. call `solve_alpha` at the bracket endpoints
3. verify the requested `CL_target` is bracketed
4. iterate with secant or guarded interpolation
5. stop when:
   - CL error is within tolerance
   - iteration limit is hit
   - convergence degrades near stall

This path must not silently extrapolate beyond the converged region.

## Fallback Policy

If the target-CL solve cannot bracket or converge safely, the worker must fall back conservatively.

Recommended fallback:

- run a local `mini alpha sweep`
- centered around the last good bracket or initial alpha estimate
- use the best converged point as a lower-bound result

The fallback result must be clearly labeled, for example with:

- `status = "mini_sweep_fallback"`
- `target_cl_converged = false`
- `clmax_is_lower_bound = true`

The screening path must never fabricate a point above effective stall.

## Pipeline Integration

The cleanest integration point is:

- keep the current concept evaluation as the screening pass
- rerun only finalists after the first ranking pass

The pipeline should therefore work in two passes:

1. run all concepts through screening fidelity
2. rank them
3. pick top `L`
4. rerun those finalists with `full_alpha_sweep`
5. rebuild airfoil feedback / summaries for those finalists
6. optionally rerank the finalist subset before final bundle writing

This allows the existing bundle and reporting flow to remain mostly intact.

## Selection / Ranking Intent

Phase 1 does not change the high-level design objective.

It only changes:

- how cheaply the screening pass gathers 2D airfoil evidence
- when the expensive full-polar information is paid for

So the expected behavior is:

- screening ranking may be approximate
- finalist ranking becomes the higher-confidence result

## Artifact Expectations

Artifacts should remain explicit about which fidelity produced them.

At minimum, concept outputs should be able to tell:

- whether a worker result came from screening or finalist analysis
- whether it came from target-CL solve or full sweep
- whether fallback occurred

This is important for later engineering review so the user can distinguish:

- a fast screening verdict
- from a full-polar finalist verdict

## Phase 1 Boundaries

This design intentionally does not include:

- replacing the whole worker stack
- introducing a different airfoil toolchain
- full coarse-to-fine optimizer search
- changing the current Birdman aerodynamic objective

Phase 1 is only:

- dual-track fidelity
- target-CL screening
- finalist full-polar reevaluation
- explicit cache separation

## Success Criteria

This phase is successful when all of the following are true:

- screening candidates no longer default to full alpha sweep
- finalists still receive full polar analysis
- screening and finalist cache entries are physically separated
- fallback behavior is explicit and conservative
- cold-run wall-clock time decreases materially versus the current full-sweep-everywhere baseline
- ranking and safety outputs remain internally consistent
