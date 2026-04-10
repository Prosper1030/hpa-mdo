# Direct Dual-Beam V1 Research Notes

Generated: 2026-04-10 CST

## Scope

This note records the engineering research and V1 implementation decision for
the experimental direct dual-beam optimizer path. The production
equivalent-beam optimizer remains unchanged.

## Evidence Used

- Equivalent-beam ANSYS validation: `docs/ansys_equivalent_beam_validation_pass.md`
- Dual-spar spot-check workflow and refined-design result:
  `docs/dual_spar_spotcheck_workflow.md`,
  `output/blackcat_004_dual_beam_refinement/ansys_refined/spotcheck_summary.txt`
- Internal dual-beam ANSYS comparison:
  `output/blackcat_004_internal_dual_beam_smoke_with_ansys/dual_beam_internal_report.txt`
- Guardrail experiment:
  `output/guardrail_experiment/guardrail_summary.json`
- Hybrid and path benchmarks:
  `output/dual_beam_refinement_baseline/dual_beam_refinement_report.txt`,
  `output/dual_beam_path_benchmark_baseline/benchmark_summary.json`
- New V1 run:
  `output/direct_dual_beam_v1_baseline/direct_dual_beam_v1_report.txt`,
  `output/dual_beam_path_benchmark_v1_baseline/benchmark_summary.json`

## Phase 1: Physics And Material Mechanism

### Verified observations

1. Equivalent-beam internal vs equivalent-beam ANSYS is already a pass. The
   simplified model is internally consistent.
2. Equivalent-beam vs dual-spar ANSYS is a model-form issue, not a load or mass
   mapping issue. In the original internal dual-beam comparison, internal
   dual-beam matched dual-spar ANSYS within about 0.6% for tip and max UZ, while
   reaction and mass were also consistent.
3. The active dual-beam displacement location is the rear spar at the outboard
   tip node. Equivalent optimum internal dual-beam:
   - tip(main): 2837.6 mm
   - max UZ / rear tip: 3373.7 mm
   - rear/main tip ratio: 1.1889
4. The simple rear/main radius guardrail increased mass by about 3.3% but made
   dual-beam max UZ slightly worse. This shows that a ratio guardrail is not
   targeting the high-leverage mode.
5. Hybrid refinement improved the actual dual-beam response:
   - mass: 9.455 kg -> 9.872 kg
   - tip(main): 2837.6 mm -> 2457.0 mm
   - max UZ: 3373.7 mm -> 2950.6 mm

### Local sensitivity study around the equivalent optimum

Perturbation: +5% on individual segment variables.

Most important radius sensitivities:

| Variable | Mass delta | tip(main) delta | max UZ delta | Interpretation |
| --- | ---: | ---: | ---: | --- |
| main radius seg 3 | +0.73% | -4.30% | -3.62% | high leverage |
| main radius seg 4 | +0.80% | -6.47% | -5.44% | highest single-segment leverage |
| main radius seg 5 | +0.60% | -2.17% | -1.85% | useful but secondary |
| rear radius seg 6 | +0.25% | +0.04% | -1.66% | directly reduces rear amplification |
| rear radius seg 5 | +0.26% | -0.25% | -0.62% | secondary rear-tip leverage |

Group sensitivities:

| Group | Mass delta | tip(main) delta | max UZ delta | Notes |
| --- | ---: | ---: | ---: | --- |
| main radius seg 3-4 | +1.53% | -10.73% | -9.03% | best bending leverage, but taper requires carrying upstream radius |
| main radius seg 5-6 | +0.98% | -1.90% | -1.78% | smaller global effect |
| rear radius seg 5-6 | +0.51% | -0.30% | -2.31% | best rear amplification knob, but rear taper constrains it |
| all main radii | +3.71% | -13.13% | -11.23% | close to hybrid behavior |
| all rear radii | +1.40% | -0.73% | -2.67% | controls ratio more than main bending |
| all radii | +5.11% | -13.69% | -13.75% | robust but heavier |

### Dominant mechanism

The response is primarily a bending/load-transfer coupling problem after the
wire support, with a rear-spar outboard amplification mode. It is not mainly a
global mass or reaction error.

The high-leverage main-spar region is segments 3-4. Because the production
manufacturing constraint enforces monotonic radius taper, increasing segment 3
or 4 alone is not a clean physical design move; the upstream equal-radius group
must move with it. This is why the V1 parameterization uses a `main_s1_4`
radius scale rather than a free segment 3/4 knob.

The rear spar is different. The rear baseline radius is already flat at the
minimum across all six segments. Any outboard-only rear radius increase would
violate taper unless the upstream rear spar also grows. This makes a
taper-preserving `rear_radius_scale` a more realistic V1 knob than a free rear
tip radius variable.

### Material and section observations

The equivalent optimum has all wall thicknesses at the 0.8 mm lower bound. Its
thin-wall ratios are not near the upper t/r guard:

| Segment | main t/r | rear t/r | EI main / EI rear |
| --- | ---: | ---: | ---: |
| 1-4 | 0.026 | 0.080 | 31.2 |
| 5 | 0.035 | 0.080 | 13.0 |
| 6 | 0.053 | 0.080 | 3.5 |

For thin circular tubes, radius is much more efficient than thickness for EI
and GJ near the current design. Thickness changes were consistently lower
leverage for displacement per mass. V1 therefore keeps thickness as a reserve
scale variable but expects radius scales to do the real work.

### Internal dual-beam caveats

Internal dual-beam and dual-spar ANSYS agree well for the inspected model, but
both are still idealized:

- Rigid rib links are infinitely stiff at joint nodes.
- Links are placed at segment/joint stations, not at every physical rib bay.
- Outboard rear tip motion is therefore sensitive to the assumed link topology.
- Stress extraction remains non-gating for ANSYS spot checks.

These caveats argue against immediately replacing hybrid with direct dual-beam
as production default.

## Phase 2: Optimizer Plan

### V1 design variables

V1 uses four reduced scale variables:

1. `main_s1_4_radius_scale`: scales main spar segments 1-4 together.
2. `main_s5_6_radius_scale`: scales main spar segments 5-6 together.
3. `rear_radius_scale`: scales all rear spar radii together.
4. `wall_thickness_scale`: reserve variable for all wall thicknesses.

This is intentionally not full 24D. The 24D space allows many low-leverage or
manufacturing-hostile moves and makes COBYLA spend effort on variables that do
not control the dominant mode.

### Strategy

V1 uses:

- equivalent optimum as the seed;
- deterministic coarse search in the 4D reduced scale space;
- local COBYLA refinement in dimensionless scale units;
- feasibility-first archive, so the final accepted design is the best feasible
  candidate seen, even if COBYLA's final point is infeasible;
- physical margins inherited from hybrid plus added taper and thickness-step
  margins.

The default V1 target is to improve the equivalent-seeded dual-beam response by:

- tip(main): 13%
- max UZ: 12%
- rear/main tip ratio: no more than warm ratio + 0.02
- mass cap: warm dual mass + 8%

These targets deliberately match the useful hybrid improvement scale instead of
forcing the dual-beam max UZ all the way down to the equivalent-beam 2.5 m
limit in V1. The current direct path showed that using 2.5 m max-UZ as a hard
first target can drive a heavy, not-quite-feasible design.

### Success criteria

V1 success means:

- stable feasible result on the baseline case;
- mass within about 1% of hybrid, preferably not heavier;
- tip(main) and max UZ in the same engineering band as hybrid;
- no reliance on an infeasible final optimizer point;
- runtime in the same order as hybrid, not many times slower.

## Phase 3: Implementation

Added:

- `scripts/direct_dual_beam_v1.py`
- `tests/test_direct_dual_beam_v1.py`

Updated:

- `scripts/benchmark_dual_beam_paths.py` now reports four paths:
  equivalent, hybrid, current direct dual-beam, reduced direct dual-beam V1.

Production defaults are unchanged.

## Phase 4: Validation

Command:

```bash
uv run python scripts/benchmark_dual_beam_paths.py \
  --output-dir output/dual_beam_path_benchmark_v1_baseline
```

Baseline results:

| Path | Wall s | Success | Feasible | Mass kg | tip(main) mm | max UZ mm | rear tip mm | Ratio | nfev |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| equivalent | 101.17 | true | true | 9.455 | 2837.6 | 3373.7 | 3373.7 | 1.1889 | 15 |
| hybrid | 108.93 | true | true | 9.872 | 2457.0 | 2950.6 | 2950.6 | 1.2009 | 81 |
| current direct | 9.90 | false | false | 14.258 | 2154.1 | 2504.8 | 2504.8 | 1.1628 | 269 |
| direct V1 | 105.55 | true | true | 9.837 | 2455.0 | 2967.7 | 2967.7 | 1.2088 | 200 |

V1 single-run details:

- scales: main_s1_4 1.050239, main_s5_6 1.049952, rear 1.011516,
  thickness 1.000000
- coarse evaluations: 150
- coarse feasible candidates: 16
- unique analysis evaluations: 200
- local COBYLA final status was not feasible, but the feasible archive accepted
  a valid point.

## Engineering Judgment

1. Current direct dual-beam fails mainly because it uses full 24D COBYLA over a
   global box with no feasible archive and an overly strict first target. It is
   fast because it does not run the equivalent warm start, not because it has a
   mature optimizer architecture.
2. V1 is materially better than current direct: it is feasible, much lighter,
   and achieves hybrid-scale displacement improvement.
3. V1 is now fair to compare with hybrid at the architecture level. It is not
   yet clearly superior: it is slightly lighter than hybrid, has nearly the same
   tip(main), but max UZ is about 0.6% higher.
4. V1 should not be promoted to production mainline yet. It is worth continuing
   as the direct dual-beam development path.
5. Hybrid should remain the near-term main recommendation and fallback. It is
   simple, already ANSYS-spot-checked in refined form, and its behavior is easy
   to explain. Direct V1 is the next experimental branch to mature, not a
   replacement today.
