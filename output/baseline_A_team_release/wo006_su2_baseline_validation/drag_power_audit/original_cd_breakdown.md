# Original CD Breakdown

## Original Definition

The original nominal screening drag was built as:

```text
CD_total = CDi + CD0_total
CD0_total = profile_cd + CDA_nonwing / Sref
```

Evidence:

- `scripts/tier2_loaded_shape_airfoil_mvp.py:694-708`
- `docs/mission_drag_budget.md:23-27`
- `docs/mission_drag_budget.md:56-71`
- `docs/mission_drag_budget.md:206-213`

## Numeric Breakdown For The 174 W Row

Using
`output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_selected_avl_recheck.csv:3`
and `Sref=33.420059598 m^2` from
`.../runs/conservative_best/conservative_best_loaded_shape_airfoils.avl:6-8`:

| component | value | inclusion read |
|---|---:|---|
| `CDi` | `0.0127613` | AVL induced drag |
| `profile_cd` | `0.009368851143241826` | Tier2 airfoil database profile drag integrated on the selected loaded shape; this is the XFOIL-derived wing profile-drag term in the closure |
| `CDA_nonwing / Sref` | `0.003889879358796229` | lumped non-wing reserve from `0.13 / 33.420059598` |
| `CD0_total` | `0.013258730502038055` | `profile_cd + CDA_nonwing / Sref` |
| `CD_total` | `0.026020030502038057` | `CDi + CD0_total` |

Cross-check:

```text
0.009368851143241826 + 0.003889879358796229 = 0.013258730502038055
0.0127613 + 0.013258730502038055 = 0.026020030502038057
```

## What Is Inside This CD

| item | inside `CD_total=0.02602003`? | basis |
|---|---|---|
| XFOIL/Tier2 wing profile drag | yes | represented by `profile_cd` |
| AVL induced drag | yes | represented by `CDi` |
| tail / fairing / hub / pylon / fuselage / misc parasite drag | yes, but only as a lumped reserve | represented by `CDA_nonwing / Sref`, not by resolved geometry-specific CFD |
| whole-aircraft empirical correction factor | no separate factor found | only the non-wing reserve is added |
| propeller efficiency | no | kept outside CD; see `docs/mission_drag_budget.md:39-52` |
| drivetrain efficiency | no | kept outside CD; see `docs/mission_drag_budget.md:46-52` |
| generic safety margin inside nominal CD | no | the nominal row uses the raw formula above |

## What Is Not Inside The Nominal 174 W Row

- The later team-release tail placeholder delta
  (`tail_cd0_increment = 0.002352`, `tail_profile_power_increment_w = 13.33234`)
  is not inside the original nominal `CD_total=0.02602003`; it appears later in
  `output/baseline_A_team_release/margin_budget.md:45-47`.
- The separate conservative power value
  `P_crank_conservative=178.8818396527458` is not a new CD definition. It is
  the same closure with only `CDi` increased by 5%; see
  `scripts/tier2_loaded_shape_airfoil_mvp.py:706-708` and `:973-976`.

## Engineering Read

This original `CD_total` is already a hybrid closure term. It mixes:

- a wing-only 3D induced term from AVL,
- a wing-profile term derived from Tier2/XFOIL-style airfoil polars,
- and a whole-aircraft non-wing reserve.

That is useful for early screening, but it is not identical to a physical wing
CFD coefficient, and it should not be treated as if every component came from a
single consistent aerodynamic model.
