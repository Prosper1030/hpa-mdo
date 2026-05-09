# Current Pathfinder Rib / Torsion Local Validation Shortlist

> Date: 2026-05-10
> Candidate: `current_avl_compromise_conservative_closed`
> Fast physical model basis: `link_limited_torsion_cell_v2`
> Verification basis: `fast_physical_model_verified_within_5pct`

## Executive Lock

The current rib / torsion pathfinder basis is now locked to:

`eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`

Verdict:

`selected_candidate_ready_for_detailed_local_validation`

This is a transition from fast design search into local validation preparation.
It is not a new fast-model retune and it is not a final aircraft pass.

The verified-within-5pct evidence means the fast physical model is aligned to
the current local CCX beam-frame torsional stiffness / shear-transfer response
for representative structural rows. It does not certify adhesive peel, collar
contact, tube-wall crushing, local buckling, skin sag, coupon allowables, flight
load factors, or final aero-surface twist.

## Evidence Basis

Primary evidence:

- `docs/reports/2026-05-09_current_pathfinder_rib_torsion_design_search.md`
- `docs/reports/2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md`
- `docs/reports/2026-05-09_positive_torque_zone_local_validation_package.md`
- `output/current_pathfinder_rib_torsion_design_search_calibrated/shortlist_calibrated.csv`
- `output/current_pathfinder_rib_torsion_fem_calibration/rib_torsion_fem_calibration_summary.json`
- `output/current_pathfinder_positive_torque_zone_validation/positive_zone_local_validation_package.json`

Key calibration facts:

| item | value |
|---|---:|
| calibrated selected case | `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` |
| revised fast selected bounded twist | `1.673592 deg` |
| selected 10 mm representative revised error | `4.553835 %` |
| aggressive collar representative revised error | `1.171407 %` |
| revised selected candidate error | `1.950437 %` |
| CCX local model audit | `ccx_local_model_reasonable_for_fast_physics_alignment` |
| primary solver evidence | `calculix_ccx_local_frame_fem` |
| critical local station | `y = 2.327757 m` |
| local torque row | `-12.716 N*m` |
| main / rear torque-couple force | `-23.839 / +23.839 N` |

Engineering read: the fast model is now good enough to choose and rank local
validation cases. The next question is no longer "which fast GJ correction is
right?" It is "can the collar, cap, bondline, skin, and spar tube physically
carry this load path with acceptable local margins and repeatable fabrication?"

## Detailed Validation Shortlist

Three cases should enter detailed local validation. The first is the locked
pathfinder basis; the other two bracket reserve and manufacturability.

| priority | role | case | mass kg | mass delta vs balsa kg | managed CG m | uncomp. CG m | H-tail trim impact deg | bounded twist deg | direct fast twist deg | manuf. score |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | selected pathfinder basis | `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` | `5.715042` | `+2.685371` | `0.750000` | `0.792135` | `4.792985` | `1.673592` | `2.782336` | `0.55` |
| P2 | conservative / heavier reserve | `eps_balsa_cap_hybrid_10mm__t12p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` | `6.788050` | `+3.758379` | `0.750000` | `0.788576` | `4.792985` | `1.451738` | `2.413505` | `0.50` |
| P3 | lower-complexity collar alternate | `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__glass_face_collar_y2p328__rear75` | `5.785042` | `+2.755371` | `0.750000` | `0.791903` | `4.792985` | `1.720516` | `2.860345` | `0.61` |

The final CG row is managed to `0.75 m` in all three cases, with the same
screening rebalance distance `0.079276 m`, static margin `0.094301`, and
`C_n_beta = 0.014030`. The uncompensated CG column is included because it shows
where the rib/collar mass wants to move the aircraft before the managed CG
bookkeeping is applied.

The lower-complexity case is not lighter; it is selected because it preserves
the same `uniform_0p30` spacing while replacing the carbon collar with a
glass-face collar and increasing manufacturability score from `0.55` to
`0.61`. The only lighter shortlisted row,
`eps_balsa_cap_hybrid_10mm__t8p0mm__dense_torque_zone_0p20__carbon_face_collar_y2p328__rear75`,
is not promoted into the detailed validation shortlist because it saves only
about `0.129 kg` relative to the selected case while relying on dense
`0.20 m` torque-zone spacing, dropping manufacturability score to `0.38`, and
raising direct fast twist to `2.962265 deg`, very close to the `3 deg`
screening bound.

## Candidate Detail Cards

### P1 Selected Pathfinder Basis

- Material / thickness: `eps_balsa_cap_hybrid_10mm`, `10.0 mm` screening rib
  core thickness.
- Cap / collar basis: EPS shape core with balsa/cap local reinforcement plus
  `carbon_face_collar_y2p328`.
- Rib spacing: `uniform_0p30`, effective spacing `0.300 m`.
- Rear-spar participation: `bounded_75pct_screening`.
- Fast physical model components: thickness factor `1.000000`, spacing factor
  `1.000000`, local reinforcement factor `1.100000`.
- Mass / CG / trim: rib mass `5.715042 kg`; `+2.685371 kg` versus balsa
  baseline; managed CG `0.75 m`; uncompensated CG `0.792135 m`; H-tail trim
  impact `4.792985 deg`; V-tail margin impact `16.716831 deg`.
- Revised bounded twist: `1.673592 deg`.
- Direct stress-test warning: direct fast twist `2.782336 deg` clears the
  screening bound in the revised fast loop, but direct projection remains a
  stress-test proxy. It is not a qualified aero-surface twist measurement and
  does not close bond, collar, tube-wall, buckling, or skin sag.
- Manufacturing complexity: medium. The uniform rib pitch is simple, but the
  carbon face collar at the torque-critical station must be treated as a real
  load-introduction part with contact width, ply/fiber orientation, bondline,
  and tube-wall bearing details.
- Local FEM / coupon priority: P1. Run this first at y=`2.327757 m` with the
  full collar / cap / bond / tube-wall local detail. This is the current
  pathfinder basis.

### P2 Conservative / Heavier Reserve

- Material / thickness: same `eps_balsa_cap_hybrid_10mm` family with `12.0 mm`
  screening thickness override.
- Cap / collar basis: same `carbon_face_collar_y2p328`.
- Rib spacing: `uniform_0p30`, effective spacing `0.300 m`.
- Rear-spar participation: `bounded_75pct_screening`.
- Fast physical model components: thickness factor `1.152820`, spacing factor
  `1.000000`, local reinforcement factor `1.100000`.
- Mass / CG / trim: rib mass `6.788050 kg`; `+3.758379 kg` versus balsa
  baseline; managed CG `0.75 m`; uncompensated CG `0.788576 m`; H-tail trim
  impact `4.792985 deg`; V-tail margin impact `16.716831 deg`.
- Revised bounded twist: `1.451738 deg`.
- Direct stress-test warning: direct fast twist `2.413505 deg` has more reserve
  than P1, but the extra stiffness can also increase local load introduction
  demand at the collar and bond. Do not read lower twist as lower local stress.
- Manufacturing complexity: medium-high. Same carbon collar work as P1 plus
  thicker rib/cap build and higher rib mass; useful as a margin reserve, not as
  the default unless P1 local margins are weak.
- Local FEM / coupon priority: P2. Use after P1 or in parallel with the same
  model setup to answer whether thickness reserve buys real local margin or
  simply moves the weak link into adhesive peel / collar bearing / tube wall.

### P3 Lower-Complexity Collar Alternate

- Material / thickness: same `eps_balsa_cap_hybrid_10mm`, `10.0 mm`.
- Cap / collar basis: EPS+balsa/cap rib with `glass_face_collar_y2p328`.
- Rib spacing: `uniform_0p30`, effective spacing `0.300 m`.
- Rear-spar participation: `bounded_75pct_screening`.
- Fast physical model components: thickness factor `1.000000`, spacing factor
  `1.000000`, local reinforcement factor `1.070000`.
- Mass / CG / trim: rib mass `5.785042 kg`; `+2.755371 kg` versus balsa
  baseline; managed CG `0.75 m`; uncompensated CG `0.791903 m`; H-tail trim
  impact `4.792985 deg`; V-tail margin impact `16.716831 deg`.
- Revised bounded twist: `1.720516 deg`.
- Direct stress-test warning: direct fast twist `2.860345 deg` clears the fast
  screening bound but has less reserve than the carbon-collar selected case.
  This row should not be promoted if coupon scatter or geometry tolerances make
  the glass collar weak in peel, bearing, or torsional shear transfer.
- Manufacturing complexity: lower than P1 by the current manufacturability
  scoring (`0.61` vs `0.55`) because it avoids the carbon collar while keeping
  uniform spacing. It is a practical build alternative, not a stronger design.
- Local FEM / coupon priority: P3. Run after P1 to keep a fabrication fallback
  if carbon collar details are expensive, brittle, or hard to bond repeatably.

## Detailed Local Validation Scope

### Torque-Critical Rib / Collar / Bond / Tube-Wall Zone

Use the positive y≈`2.328 m` package as the first local validation window.

- Critical station: R068 at y=`2.327757 m`.
- Active ribs: R067 / R068 / R069.
- Active bays: B066 / B067 / B068 / B069.
- Local boundary ribs: R066 and R070.
- Local load row: main lift `21.202169 N`, kernel torque `-12.715548 N*m`.
- Torque couple: main / rear vertical forces `-23.839355 / +23.839355 N`.

The FEM model must include the main/rear spar local tube segments, collar
contact/load-introduction width, rib cap/web load path, adhesive bondline, and
enough neighboring bay length to avoid pretending the collar is attached to an
infinitely rigid structure.

### Skin Sag / Shape Retention

The selected basis uses nominal `0.30 m` bays and the materialized audit already
shows the current physical rib station set reaches max bay `0.297063 m`. That
does not prove the skin holds the airfoil.

Required checks:

- 0.30 m bay skin panel deflection under covering tension, pressure, handling,
  and realistic local support assumptions.
- Shape retention with EPS core treated as shape support, not as structural
  torsion bracing unless coupon evidence supports it.
- Comparison between torque-critical bay and at least one representative
  ordinary bay away from collar / wire / transition details.

### Rib-to-Spar Bond Shear and Peel

Required missing data before margin claims:

- adhesive shear allowable and peel / mixed-mode allowable,
- bondline width, thickness, fillet, and surface prep assumptions,
- lap length or collar tab geometry,
- load direction split between main-spar bond, rear-spar bond, and cap/collar
  bearing.

Bond shear alone is not enough; peel must be checked because the local
torque-couple creates opening / prying risk at the collar and cap ends.

### Carbon Collar / Balsa Cap Load Path

The fast model treats collar credit as a capped shear-link contribution, not as
free global GJ. Detailed validation must explicitly follow:

```text
skin / rib web
-> balsa/cap strip shear transfer
-> carbon or glass face collar
-> adhesive / contact patch
-> main and rear spar tube wall
```

Open questions:

- Does the cap strip carry diagonal shear without local balsa/EPS crushing?
- Does the collar introduce load into the tube over a long enough width to
  avoid local bearing hot spots?
- Does the carbon-collar P1/P2 route create a stiffer but more brittle load
  path than the P3 glass-collar route?

### Tube Wall Local Crushing / Ovalization

The current CCX calibration reports tube-wall margin around `2.303946` for the
representative structural rows, but that is still a simplified beam-frame
indicator. Detailed validation must replace it with local tube-wall geometry,
wall thickness, material allowables, collar pressure/contact, and local
ovalization / bearing checks.

Required outputs:

- tube-wall bearing / local crush margin,
- ovalization sensitivity under torque-couple and collar clamp/bond pressure,
- comparison between main and rear tube load introduction,
- note whether a local sleeve, wrap, doubler, or wider collar is required.

### Representative Ordinary Bay

Do not validate only the hot spot. Add one ordinary bay case with nominal
`0.30 m` spacing and no special torque collar to determine whether:

- skin sag is a global bay problem rather than only a torque-zone problem,
- EPS+balsa cap manufacturing scatter changes ordinary-bay stiffness,
- ordinary bay bond details are safe enough to support the selected rib pitch.

## FEM / Coupon Plan

Recommended order:

| step | output | success criterion |
|---|---|---|
| 1 | Geometry and allowable freeze sheet | No placeholder values for adhesive, collar, tube, balsa/cap, EPS, skin, bondline, or contact width. |
| 2 | P1 local FEM pre-margin run | Reactions close, deformation mode matches torsion / shear-transfer expectation, stress extraction locations are stable under mesh refinement. |
| 3 | P1 coupon matrix | C01-C07 coupon or supplier allowables mapped to the same failure modes used by FEM. |
| 4 | P1 local margin report | Bond shear, peel, collar bearing, tube crush/ovalization, cap shear transfer, and skin sag all reported with margins and units. |
| 5 | P2 reserve comparison | Shows whether extra thickness improves real local margin without causing worse peel / bearing / tube-wall demand. |
| 6 | P3 manufacturability fallback | Shows whether the glass-collar alternate is acceptable if carbon collar workmanship or allowables are not credible. |
| 7 | Ordinary bay validation | Confirms 0.30 m bay skin sag and ordinary rib-to-spar details are not the hidden weak link. |

Coupon matrix to preserve from the positive-zone package:

- `C01_eps_balsa_cap_shear_transfer`
- `C02_main_spar_bond_shear`
- `C03_rear_spar_bond_shear`
- `C04_bond_peel`
- `C05_collar_bearing`
- `C06_tube_wall_crush_ovalization`
- `C07_skin_sag_shape_keeping_panel`

## Engineering Warnings

- Lower twist is not automatically safer. A stiffer collar/rib can push the
  same torque into a smaller bond or tube-wall contact patch.
- The current local load row is a screening row. Final detail validation must
  decide whether load factor, dynamic allowance, handling loads, or asymmetric
  torsion should amplify it.
- `rear_spar_participation=bounded_75pct_screening` is still a screening
  participation assumption, not a measured rear-spar load-sharing proof.
- The P3 glass-collar alternate is a manufacturability fallback. It is not a
  reason to weaken the selected load path without coupon evidence.
- The rejected 8 mm dense row is useful as a sensitivity note, but it should not
  distract the first detailed validation pass from the locked selected basis.

## Final Boundary

Current verdict:

`selected_candidate_ready_for_detailed_local_validation`

Not claimed:

- final aircraft pass,
- final FEM/APDL margin pass,
- adhesive / bond sign-off,
- tube-wall / collar sign-off,
- skin sag / shape-retention sign-off,
- buckling sign-off,
- manufacturing release.

Next concrete work: fill the missing geometry / supplier / coupon allowables,
run the P1 y≈`2.328 m` detailed local FEM and coupon checks, then compare P2
and P3 as reserve / manufacturing alternates.
