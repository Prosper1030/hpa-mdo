# Origin SU2 High-Quality Upgrade Design

**Goal**

Upgrade the current repo-owned `origin.vsp3 -> SU2` path from a
`can-run` baseline into a `credible-for-comparison` aerodynamic workflow,
while keeping `origin.vsp3` as the geometry truth and explicitly confirming
that the current whole-aircraft path includes the horizontal and vertical tail.

**Current Verified Baseline**

- Geometry truth is the repo-owned [`data/blackcat_004_origin.vsp3`](/Volumes/Samsung%20SSD/hpa-mdo/data/blackcat_004_origin.vsp3),
  wired via [`configs/blackcat_004.yaml`](/Volumes/Samsung%20SSD/hpa-mdo/configs/blackcat_004.yaml)
  and consistent with [`docs/avl_aero_gate_contract.md`](/Volumes/Samsung%20SSD/hpa-mdo/docs/avl_aero_gate_contract.md).
- `origin.vsp3` introspection currently detects:
  - `Main Wing`
  - `Elevator`
  - `Fin`
- The current VSPAero path also shows the empennage in solver ingest:
  - `Surface 3/4 = Elevator_C`
  - `Surface 5 = Fin_C`
- The current SU2 path can now:
  - export full-geometry STEP/STL from `origin.vsp3`
  - auto-mesh an external-flow tetra volume
  - prepare and run a real single-alpha SU2 case
  - read `history.csv` back into the shared aero bundle

**What The Current Baseline Is Good For**

- proving the `origin -> export -> mesh -> SU2 -> parse` chain is alive
- checking marker contract and history parsing
- getting a first-pass whole-aircraft `CL / CD / CM / Lift / Drag` output

**What The Current Baseline Is Not Good Enough For**

- trustworthy drag comparison against higher-quality CFD
- mesh-converged aerodynamic decision-making
- boundary-layer-sensitive interpretation
- claiming "like the fairing project" quality yet

## Evidence About Tail Coverage

The current path is not wing-only.

1. `vsp_introspect.py` walks all OpenVSP `WING` geoms and classifies them into
   `main_wing`, `horizontal_tail`, and `vertical_fin`.
2. The current reference aircraft resolves to:
   - `main_wing = Main Wing`
   - `horizontal_tail = Elevator`
   - `vertical_fin = Fin`
3. The VSPAero solver-side smoke also lists:
   - `Surface 3/4 = Elevator_C`
   - `Surface 5 = Fin_C`
4. STEP/STL export uses `SET_ALL`, so the CFD geometry export is also
   whole-aircraft, not wing-only.

One current limitation should be called out explicitly:

- the tail geometries are present
- but the current `origin.vsp3` extraction still reports `controls=0` for both
  the horizontal tail and the fin in the introspection summary

So the right statement is:

- **tail geometry coverage is confirmed**
- **control-surface contract coverage is not yet confirmed**

## Three Upgrade Paths

### Path A: Keep tuning the current STL external box baseline

This is the fastest path, but it is the wrong quality ceiling. The current mesh
builder is intentionally lightweight and uses:

- STL import
- a simple farfield box
- isotropic tetra meshing
- distance-based sizing

This is enough for plumbing validation, but not the right long-term route for
high-quality aerodynamic drag work.

### Path B: Upgrade the repo-native Gmsh + SU2 route into a quality workflow

This is the recommended path.

Keep the current repo-owned origin workflow and improve the weakest links:

- geometry cleanliness
- surface/volume mesh quality
- near-wall treatment
- wake refinement
- convergence discipline
- mesh-study discipline

This path gives the best tradeoff between:

- quality
- maintainability
- keeping the workflow inside the current repo
- avoiding a hard dependency on an external meshing stack too early

### Path C: Replace the current path with a heavier fairing-style external route

This likely has the highest long-term ceiling, but it is premature right now.
The repo already has a working native `origin -> SU2` path, so the better move
is to improve that path first before introducing a second, heavier workflow.

## Recommended Design

Use **Path B** and split the work into four stages.

### Stage 1: Freeze the geometry-coverage and solver contract

Before increasing fidelity, make the current contract explicit and durable.

Deliverables:

- a machine-readable geometry coverage artifact for `origin.vsp3`
- a documented statement that `Main Wing`, `Elevator`, and `Fin` are part of
  the current whole-aircraft aero path
- an update to `docs/hi_fidelity_validation_stack.md` so SU2 is no longer
  described as "blueprint only"
- a clear distinction between:
  - whole-aircraft coefficients
  - wing strip loads
  - geometry present vs. controls extracted

Acceptance criteria:

- a smoke artifact or report can show tail presence without re-reading raw logs
- the repo docs no longer understate the current SU2 status

### Stage 2: Replace the mesh with a quality-oriented external-flow mesh

This is the highest-value technical step.

The current auto-mesh path should evolve from:

- `STL + box + isotropic tetra`

to something closer to:

- cleaner CAD-backed geometry when possible
- component-aware surface sizing
- near-body boundary-layer treatment
- wake-directed refinement downstream of the aircraft
- repeatable coarse/medium/fine mesh variants for study

Recommended direction:

- prefer STEP/BREP/OCC-backed meshing over raw STL whenever the geometry is
  clean enough
- keep STL as a fallback, not the preferred high-quality path
- expose mesh presets instead of a single free-form option blob

Minimum quality-oriented presets:

- `baseline`
- `study_coarse`
- `study_medium`
- `study_fine`

Each preset should lock:

- farfield extents
- surface size targets
- volume size targets
- near-body growth behavior
- wake refinement settings

Acceptance criteria:

- the mesh generator can produce at least three repeatable study meshes
- all study meshes preserve the `aircraft` / `farfield` marker contract
- the resulting meshes remain runnable in SU2 without manual file surgery

### Stage 3: Upgrade the SU2 runtime contract from "runs" to "comparable"

The current runner already launches and reads results. This stage makes those
results trustworthy enough to compare.

Needed upgrades:

- codify the exact history fields we require for aero analysis
- store solver settings that materially affect comparability
- report convergence state instead of just "history exists"
- attach enough metadata to reconstruct how a case was run

Required reporting fields:

- `alpha_deg`
- `CL`
- `CD`
- `CM`
- `Lift`
- `Drag`
- iteration count
- convergence reason or stop reason
- mesh preset
- geometry export path

Acceptance criteria:

- every SU2 sweep point has both aero results and run provenance
- the analysis bundle can distinguish:
  - `completed and converged`
  - `completed but weak`
  - `prepared only`
  - `failed`

### Stage 4: Add a quality gate based on mesh and trend consistency

This is where the workflow becomes decision-usable.

The quality gate should answer:

- does `CL / CD / CM` move materially between coarse/medium/fine meshes?
- do the trends against alpha make aerodynamic sense?
- does SU2 disagree with VSPAero in a way that suggests physics/model-form
  difference, or just a bad mesh/case setup?

Recommended first gate:

- single geometry
- `alpha = -2, 0, 2, 4 deg`
- three mesh levels
- compare SU2 vs VSPAero on:
  - `CL vs alpha`
  - `CD vs alpha`
  - `CM vs alpha`

Acceptance criteria:

- the repo can produce one full mesh-study bundle for `origin.vsp3`
- the bundle ends with an explicit judgment:
  - `usable for comparison`
  - `still baseline only`

## Architecture Boundaries

### Geometry ownership

- `origin.vsp3` remains the only geometry truth for this path
- geometry export should stay centralized in the current origin-CFD export path
- component/tail coverage checks should happen before meshing

### Meshing ownership

- meshing should stay in a focused module, separate from SU2 runtime logic
- mesh presets should be versioned and inspectable
- the mesh module should own marker naming and physical-group guarantees

### Solver ownership

- SU2 runtime code should own:
  - config generation
  - solver launch
  - convergence metadata
  - history discovery
- it should not own geometry classification or CAD cleanup

### Analysis ownership

- the shared aero bundle should stay solver-agnostic
- VSPAero and SU2 should land in the same normalized table shape
- comparison logic should sit above both solvers, not inside either backend

## Risks

### Risk 1: The current STL path can mask geometry-quality problems

Even if SU2 runs, poor triangulation or disconnected surfaces can make the
result look stable while still being low quality. That is why STEP/OCC-backed
meshing should become the preferred path.

### Risk 2: Tail geometry present does not automatically mean tail loads are trustworthy

Tail presence is confirmed, but high-quality empennage force prediction still
depends on mesh quality and solver setup near the tail surfaces.

### Risk 3: It is easy to over-claim quality after the first successful mesh study

The first successful mesh study should be treated as:

- a comparability milestone

not as:

- final aerodynamic truth

## What This Design Does Not Try To Solve Yet

- control-surface deflection sweeps
- turbulence-model exploration
- full fairing-project parity in one round
- automatic wake/body-layer tuning for every future geometry
- replacing the existing structural high-fidelity route

## Recommendation

Proceed with Path B and implement in this order:

1. Freeze geometry/tail coverage contract and update stale docs.
2. Build quality-oriented mesh presets and a three-level mesh study path.
3. Strengthen the SU2 run/report contract to capture convergence quality.
4. Produce one `origin.vsp3` mesh-study bundle and judge whether the route has
   crossed from `baseline only` to `usable for comparison`.
