# Dual-Beam Benchmark Ladder

## Purpose

This ladder is designed to answer one question cleanly:

> Can the current internal dual-beam structural model reproduce the right external-beam or external-FEM behavior when geometry, loads, boundary conditions, and ownership are frozen rung by rung?

It is intentionally not:

- a broad optimization campaign,
- a new production gate,
- a justification for changing ranking or hard constraints,
- or permission to tune production equations by eyeballing one old ANSYS case.

## Why This Ladder Is Necessary

The repo already contains three different kinds of evidence:

- equivalent-beam parity evidence,
- explicit two-beam inspection evidence,
- shell-mesh local spot-check evidence.

Those are all useful, but they answer different questions.

The ladder below forces the calibration work to separate:

1. basic beam math,
2. explicit two-beam load sharing,
3. wire-support behavior,
4. torque ownership,
5. and finally one frozen production-like case.

Without that ordering, a mismatch in the final production case would be too ambiguous. It could come from:

- wrong `EI`,
- wrong taper mapping,
- wrong wire support,
- wrong torque ownership,
- wrong load replay,
- or just shell-mesh artifacts.

## Rung Order

1. Benchmark 1: simple cantilever single tube
2. Benchmark 2: tapered single tube
3. Benchmark 3: dual beam without wire
4. Benchmark 4: dual beam with wire
5. Benchmark 5: dual beam with lift + `Cm` torque
6. Benchmark 6: one frozen smooth-tier2 production-like case

Do not skip ahead. If a lower rung fails, higher rungs cannot be interpreted cleanly.

## Benchmark 1: Simple Cantilever Single Tube

- Geometry:
  - straight half-span beam
  - constant radius and thickness
  - no rear spar
  - no wire
- Internal target:
  - equivalent-beam path using the same current section and FEM utilities
- External target:
  - ANSYS BEAM188 or CalculiX beam-element deck
- Loads:
  - uniform distributed vertical load only
  - no aerodynamic torque
- Boundary conditions:
  - fixed root
- Compare first:
  - tip deflection
  - root reaction
  - beam mass
- Why it exists:
  - this is the fastest way to catch unit, `EI`, load-integration, or fixed-root mistakes
- Suggested interpretation band:
  - reaction and mass should be near machine-clean
  - deflection should be very close because the problem is canonical

## Benchmark 2: Tapered Single Tube

- Geometry:
  - same straight cantilever family as Benchmark 1
  - tapered radius and or thickness
- Internal target:
  - equivalent-beam path with the repo’s current segment-to-element mapping
- External target:
  - ANSYS or CalculiX beam deck with the same taper contract
- Loads:
  - uniform distributed vertical load only
- Boundary conditions:
  - fixed root
- Compare first:
  - tip deflection
  - root reaction
  - beam mass
- Why it exists:
  - Benchmark 1 can pass even if taper interpolation is wrong
  - Benchmark 2 specifically tests spanwise `EI` integration and segment midpoint handling

## Benchmark 3: Dual Beam Without Wire

- Geometry:
  - front spar + rear spar
  - fixed spar separation
  - rigid rib links
  - no wire
- Internal target:
  - `dual_spar_ansys_parity` first
  - optional `dual_beam_production` no-wire, no-`Cm` sensitivity sidecar
- External target:
  - ANSYS or CalculiX beam deck with two beams and rigid links
- Loads:
  - distributed lift only
  - no torque
- Boundary conditions:
  - root fixed on both spars
- Compare first:
  - main-tip deflection
  - rear-tip deflection
  - max `|UZ|`
  - support reaction
  - beam mass
- Why it exists:
  - this is the first rung where front/rear load sharing and rear amplification can appear
  - it isolates link topology and explicit two-beam behavior before wire or torque is added

## Benchmark 4: Dual Beam With Wire

- Geometry:
  - same two-beam geometry as Benchmark 3
  - add one wire attachment and anchor definition
- Internal target:
  - `dual_beam_production`
  - optional parity-style vertical-support fallback only for diagnosis
- External target:
  - beam-element deck with explicit cable/truss support if the solver supports it
  - if not, use a documented support surrogate and label it as such
- Loads:
  - distributed lift only
  - no torque
  - include pretension when the internal and external model both support it
- Boundary conditions:
  - fixed root on both spars
  - wire active
- Compare first:
  - tip deflection reduction versus Benchmark 3
  - support reaction partition
  - wire tension or support reaction
  - main/rear tip ratio
- Why it exists:
  - the wire is a first-order HPA load-path feature
  - this rung tells us whether the explicit truss support is the main source of mismatch

## Benchmark 5: Dual Beam With Lift + `Cm` Torque

- Geometry:
  - same frozen geometry as Benchmark 4
- Internal target:
  - three ownership variants on the same geometry:
    - `main_beam_my_about_main_spar`
    - `front_rear_vertical_couple`
    - `Cm off` control
- External target:
  - beam deck variants that apply the same torque in the same frozen ways
- Loads:
  - distributed lift plus aerodynamic torque
- Boundary conditions:
  - same as Benchmark 4
- Compare first:
  - change in main-tip and rear-tip deflection by ownership mode
  - reaction partition
  - residual by axis if a moment audit is available
- Why it exists:
  - current repo evidence already says torque ownership is one of the active uncertainties
  - this rung must be resolved before any production calibration factor is proposed

## Benchmark 6: Frozen Smooth-Tier2 Production-Like Case

- Geometry:
  - freeze one current `smooth_tier2_production_baseline`-style case after a manual case review
- Internal target:
  - frozen `dual_beam_production` case
- External target:
  - first a beam benchmark deck
  - then, only after the beam deck is understood, the existing shell-plus-beam CalculiX route
- Loads:
  - use the real current spanwise load contract for the frozen case
  - prefer `spar_data.csv` if that is the authoritative replay artifact for the case
- Boundary conditions:
  - the exact root and wire contract used by the frozen internal case
- Compare first:
  - tip deflection
  - support reaction
  - main/rear tip behavior
  - contextual mass and clearance metrics
- Why it exists:
  - this is the bridge from synthetic controlled cases to one real project case
  - it should only be attempted after Benchmarks 1 to 5 pass or at least become interpretable

## Recommended Comparison Outputs

For each benchmark, Round 2 should produce:

- one frozen internal metrics JSON
- one external deck per solver and ownership variant
- one comparison row in `internal_vs_fem_comparison.csv`
- one human-readable note in `comparison_summary.md`

Each comparison row should at minimum include:

- benchmark id
- internal model family
- external solver
- geometry label
- load label
- BC label
- tip deflection
- rear-tip deflection if applicable
- support reaction
- mass
- torque ownership mode
- pass / warn / fail label
- interpretation note

## Engineering Rules For The Ladder

- Do not fit calibration factors on Benchmark 6 if Benchmarks 1 to 5 are not already understood.
- Do not call a shell-mesh result “validation” when the equivalent beam benchmark has not been nailed down first.
- Do not allow one old ANSYS file to become the only truth source.
- Do not bury torque-ownership ambiguity inside a single scalar error metric.
- Do not change production ranking or hard gates while running this ladder.

## Expected Engineering Outcome

If this ladder is executed well, the likely outcomes are:

- some lower rungs will pass nearly exactly,
- some dual-beam rungs will reveal model-form differences cleanly,
- torque ownership will become an explicit contract decision instead of a vague suspicion,
- and the final production-like benchmark will become interpretable without pretending that one shell mesh is sacred truth.
