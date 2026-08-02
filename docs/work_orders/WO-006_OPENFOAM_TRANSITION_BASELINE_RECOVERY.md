/goal In /Volumes/Samsung SSD/hpa-mdo, obtain one RAM-safe, numerically qualified and physically defensible low-Re 3D OpenFOAM wing-drag diagnostic on the accepted Fine mesh, preferring kOmegaSSTLM and autonomously iterating through bounded SST/LM recovery attempts instead of stopping after the first failure.

Act as the CFD engineer and work controller. You may spawn subagents for
evidence mining, official-manual/paper research, and adversarial review, but do
not run more than one CFD solver process at a time. Review subagent conclusions
before changing the case.

## Required startup

Read `AGENTS.md`, `README.md`, `CURRENT_MAINLINE.md`,
`docs/AI_WORK_ORDER_PROTOCOL.md`, `docs/work_orders/QUEUE.md`, and the existing
WO-006 OpenFOAM artifacts. Run:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/check_baseline_a_data_authority.py --check-only
git status --short
```

Do not stage, overwrite, or revert unrelated dirty files. Stay on the current
branch unless the user explicitly approves integration work.

## Locked engineering basis

- Geometry, mesh, AoA, velocity direction, wall/symmetry convention, force
  patches, `Sref=33.420059598 m^2`, and `Cref=1.003721543 m` are frozen.
- Accepted numerical warning: Fine SA `CL=1.160934`,
  `CD_total_physical=0.03326556`, with Medium-to-Fine CD change about `-1.44%`.
- The pressure residual is broadly distributed on the primary upper/lower
  surfaces; patch bookkeeping, TE/tip/root/closure contamination, local Cp
  explosion, and outlet-pressure BC sensitivity have already been bounded.
- Existing SST/LM values near `CD=0.030-0.031` have only 50 force rows and are
  not accepted results. The old `pimpleFoam` probe produced no usable force
  history.
- The current diagnostic lock is `rho=1.225 kg/m^3`, `V=6.5 m/s`,
  `nu=1.4607e-5 m^2/s`, `AoA=0.18 deg`. Preserve it for the same-mesh model
  bracket. Explicitly record that the Phase J mission environment is
  `33 C / 80%RH` and requires a later same-model environment sensitivity; do
  not silently mix the two bases.
- `98.5 kg` and the current `34.332286 m` span are authority. No design-power,
  mass, geometry, or procurement update is allowed.

## Hardware boundaries

- This Mac has 16 GB physical RAM. Use serial OpenFOAM only: `--np 1`.
- Set the process-tree guard to `--max-rss-gb 10`. A memory-guard stop is a
  controlled diagnostic, not permission to rerun without the guard.
- Use `/Volumes/Samsung SSD/hpa-cfd-tmp/architecture_sensitivity`; verify at
  least 20 GB free before every solve. Do not use the nearly full system `/tmp`.
- Run one case and one 50-iteration chunk at a time. Never launch SST and LM in
  parallel. Keep `purgeWrite=2` and preserve the final checkpoint before cleanup.

## Phase 1: qualify the current evidence

1. Run the focused runner tests and `--summarize-only`.
2. Confirm the runner rejects fewer than 100 force rows, missing force history,
   and no time advance; confirm it parses CmPitch and writes a final steady
   checkpoint no more than 25 iterations apart.
3. Inspect the installed OpenFOAM-v2512 `kOmegaSSTLM` implementation, native
   tutorial BCs, and primary Langtry-Menter/OpenFOAM documentation before
   changing `omega`, `gammaInt`, or `ReThetat`. Use primary sources only.
4. Audit whether `Tu=0.5%`, `L=0.001c`, `gammaInt=1`, and
   `ReThetat=879.6744` are physical freestream inputs, tutorial-derived
   conditions, or numerical stabilization choices. Do not promote a
   numerics-only length scale as HPA atmospheric truth.

## Phase 2: bounded Fine LM recovery

Start from the existing best conservative case
`lm_Tu0p5_L0p001c_r2`. Its stored latest field is still time 2000, so the first
resumed chunk is a clean rerun from the configured LM initial fields:

```bash
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases lm_Tu0p5_L0p001c_r2 \
  --resume --iterations 50 --np 1 --max-rss-gb 10
```

After each chunk, verify all of the following before continuing:

- the solver advanced and wrote the final checkpoint;
- process-tree peak RSS stayed below the guard;
- force rows, residuals and continuity are finite;
- no catastrophic `omega`, `k`, `gammaInt`, or `ReThetat` bounding/correlation
  failure is accumulating;
- U, p, k, omega, nut, gammaInt and ReThetat fields exist and are finite;
- pressure, viscous and total force trends are moving toward a stable window.

Continue in 50-iteration chunks until there are at least 100 unique force rows
and the final-100 gate passes: CD and CL relative span below 1%, CmPitch absolute
span below 0.005. Use at most four LM chunks before changing route. You may make
bounded changes to relaxation, turbulence convection schemes, freestream decay
handling, and model-recommended inlet/field BCs when supported by logs and
primary documentation. Record each attempt, reason and outcome. Do not change
geometry, mesh, reference values, AoA or force ownership.

## Phase 3: automatic fallback without brute force

If LM still fails after the bounded attempts, do not stop with an omega error
and do not keep burning Fine iterations. Run the same resumable, serial,
100-row qualification on `sst_Tu0p5_L0p001c` as a fully turbulent upper bracket.
Then use the stable SST field as an LM warm start only if OpenFOAM field/model
compatibility is verified. A stable SST result is a useful high-drag bracket,
not final transition truth.

Do not run same-mesh physical-time `pimpleFoam`: the existing Fine near-wall
cells imply an impractical physical-time CFL requirement. Do not restart the
historical SU2 custom mixed-handoff route and do not build a new grid ladder.

## Required outputs and decision

Produce a compact committed recovery artifact containing:

- full command log and per-attempt status, elapsed time and peak RSS;
- final-100 force CSV and gate calculation;
- `CD_pressure`, `CD_viscous`, `CD_total`, `CL`, and `CmPitch`;
- yPlus upper/lower mean, max, and face percentages below 1, below 5 and above 20;
- finite-field ranges for k, omega, nut, gammaInt and ReThetat;
- transition/intermittency evidence showing whether LM predicts plausible
  laminar and transitioned regions;
- exact changed OpenFOAM dictionaries and scripts;
- comparison against accepted SA/Fine using the identical force basis;
- one verdict: `usable_as_engineering_diagnostic`,
  `stable_fully_turbulent_upper_bracket_only`, or
  `transition_route_not_established`.

Engineering success is not merely solver completion. The result must have a
qualified force window, physically interpretable transition fields, acceptable
primary-wall yPlus, and no hidden memory/disk failure. State whether turbulence
model change explains a meaningful part of the SA pressure-drag excess, but do
not update design power.

Update `README.md` and `CURRENT_MAINLINE.md` to the actual trust boundary. Run
focused tests plus the data-authority checker. Stage only this work order's
files with `git add -p` and make one scoped commit. Final response must include
the verdict, key coefficients, resource peak, changed files, verification,
engineering caveats, and a short reviewer prompt for another Codex thread.
