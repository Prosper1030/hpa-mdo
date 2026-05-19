# Drag/Power Verdict

Verdict: `needs update`

The old `174 W` number is a valid traceable screening artifact, but it should
not remain the current design-power estimate after this audit. It is definition-
mixed, pre-tail, and optimistic relative to the newer higher wing-drag CFD-like
result.

## Required Answers

1. Which script/report produced `174 W`?

   The exact computational source is `scripts/tier2_loaded_shape_airfoil_mvp.py`.
   The exact generated row is
   `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_selected_avl_recheck.csv:3`.
   That value is later propagated into
   `output/go_mode_main_wing_candidate/final_candidate_package/candidate_summary.csv:2`
   and `.../GO_MODE_DECISION.md:28-35`. The later freeze audit re-labels it as
   `Pre-tail main-wing P_crank`; see
   `output/baseline_A_team_release/design_space_freeze_audit/design_space_freeze_audit.md:38-40`.

2. What CD was used?

   `CD_total = 0.026020030502038057`

3. What components are inside that CD?

   - `CDi = 0.0127613` from AVL induced drag
   - `profile_cd = 0.009368851143241826` from the Tier2/XFOIL-style airfoil
     profile-drag integration on the selected loaded shape
   - `CDA_nonwing / Sref = 0.003889879358796229` as a lumped non-wing reserve
     for tail/fairing/hub/pylon/fuselage/misc parasite drag

   Not inside the nominal CD:

   - propeller efficiency
   - drivetrain efficiency
   - a generic safety factor
   - the later separate tail placeholder delta

   The only extra margin in the source bundle is
   `P_crank_conservative = 178.882 W`, which applies a 5% bump to induced drag
   only.

4. Is OpenFOAM `CD = 0.031823` the same definition?

   No. The original `0.02602003` is
   `AVL induced + wing profile + lumped non-wing reserve`.
   The OpenFOAM-like `0.031823` is best interpreted as a physical wing 3D CFD CD
   with induced drag already embedded, but without the original non-wing reserve
   unless you add it separately.

   Also, this checkout does not contain an accepted repo artifact that prints
   exactly `0.031823`. The nearest accepted repo value is the mirrored stable
   route `CD_primary = 0.03276165` at `CL_primary = 1.133291`.

5. Would adding induced drag to OpenFOAM double-count?

   Yes. Adding AVL `CDi` on top of OpenFOAM wing CD would double-count induced
   drag.

6. What power comes from `CD = 0.02602`?

   Using the original basis
   (`rho = 1.18 kg/m^3`, `V = 6.6 m/s`, `Sref = 33.420059598 m^2`,
   `eta_prop = 0.88`, `eta_trans = 0.96`):

   `P_crank = 174.60027944116567 W`

7. What power comes from `CD = 0.031823`?

   On that same original basis:

   `P_crank = 213.53951496025377 W`

8. Should the design power estimate stay `174 W` or be revised?

   Revised.

   Best engineering label: `needs update`.

   Reason:

   - `174 W` is only the old pre-tail screening closure.
   - It is not definition-matched to a physical wing OpenFOAM CD.
   - The newer wing-drag result is materially higher.
   - If you preserve the original non-wing reserve logic, the normalized total
     implied by `CD = 0.031823` becomes `CD = 0.035712879358796225`, which maps
     to `239.64 W`.

## Final Engineering Verdict

`174 W` should be kept only as historical screening evidence. It is not the
best current design-power estimate. The correct current call is:

- original `174 W`: traceable but optimistic
- raw `0.02602` versus raw OpenFOAM `0.031823`: not directly comparable as
  identical totals
- OpenFOAM plus AVL induced drag: invalid because of double-counting
- design-power estimate: `needs update`
