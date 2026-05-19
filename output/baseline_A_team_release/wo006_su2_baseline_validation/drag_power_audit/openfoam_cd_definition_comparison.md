# OpenFOAM CD Definition Comparison

## Scope

This comparison checks whether the original screening `CD_total=0.02602003` and
the newer OpenFOAM-like `CD_total_physical≈0.031823 at CL≈1.13` mean the same
thing.

## Accepted Repo Evidence

I did not find an accepted repo artifact that literally writes
`CD_total_physical = 0.031823`.

The nearest accepted OpenFOAM artifact in this checkout is the stable mirrored
full-wing route:

- `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_solver_stability/stable_route_smoke_report.md:3-15`
- `.../stable_force_breakdown_report.md:5-12`
- `.../pressure_viscous_split_report.md:5-10`

That accepted route reports:

- `CD_primary = 0.03276165`
- `CL_primary = 1.133291`
- `CD_total = 0.05708291`

and defines the force groups as:

```text
primary = [airfoil_upper, airfoil_lower]
total   = [airfoil_upper, airfoil_lower, physical_tip_left, physical_tip_right, te_wall]
```

So the accepted repo interpretation is:

- `CD_primary` = wing-wall drag on the physical airfoil surfaces only
- `CD_total` = wing-wall drag plus diagnostic side/tip/TE surfaces

## Definition Comparison

| quantity | what it contains | comparable to original `0.02602003`? |
|---|---|---|
| original `CD_total=0.02602003` | AVL `CDi` + Tier2/XFOIL profile drag + lumped non-wing reserve | baseline reference |
| user-supplied OpenFOAM `CD≈0.031823` at `CL≈1.13` | best interpreted as physical wing CFD drag, with induced drag already embedded, but without the original non-wing reserve | no, not the same definition |
| accepted repo `CD_primary=0.03276165` at `CL=1.133291` | physical wing-wall drag only | no, not the same definition |
| accepted repo `CD_total=0.05708291` | wing-wall drag plus diagnostic tip-side and TE surfaces | no, and it is explicitly not release-grade drag truth |

## Direct Comparability Verdict

The two CD values are **not directly comparable as identical totals**.

Why:

1. The original `0.02602003` already includes a whole-aircraft non-wing reserve
   (`CDA_nonwing / Sref = 0.003889879...`).
2. The OpenFOAM wing CD does not include that original lumped non-wing reserve
   unless you add it deliberately.
3. The original row is at `CL=1.16853`; the accepted OpenFOAM mirror route is at
   `CL=1.133291`. The lift levels are close enough for a sanity comparison, but
   not identical enough to call them exactly matched operating points.
4. The accepted OpenFOAM route is still bounded route-smoke evidence, not
   release-grade drag validation; README and CURRENT_MAINLINE both keep that
   trust boundary explicit.

## Induced Drag Double-Count Check

Adding AVL induced drag to OpenFOAM `CD_primary` or to a physical-wing
OpenFOAM `CD≈0.031823` would **double-count induced drag**.

Reason:

- In the original closure, induced drag is a separate AVL term because the
  profile drag term comes from sectional polars.
- In 3D CFD, the reported wing drag already includes the integrated pressure and
  viscous forces on the modeled wing surfaces. The induced component is already
  inside that 3D wing force result.
- `pressure_viscous_split_report.md:7-10` confirms the accepted OpenFOAM wing
  coefficient is already a full 3D force integral, not a profile-only term.

So the admissible apples-to-apples normalization is:

```text
OpenFOAM wing CD + same non-wing reserve
```

not:

```text
OpenFOAM wing CD + AVL CDi
```

## Same-Basis Power Interpretation

When the user-supplied `CD=0.031823` is mapped onto the original power basis
(`rho=1.18 kg/m^3`, `V=6.6 m/s`, `Sref=33.420059598 m^2`,
`eta_prop=0.88`, `eta_trans=0.96`), it implies `213.54 W`.

If the goal is to preserve the original whole-aircraft closure structure, the
closest normalized total is:

```text
CD = 0.031823 + 0.003889879358796229 = 0.035712879358796225
P_crank = 239.64 W
```

For the accepted repo mirror-route `CD_primary=0.03276165`, the same normalized
closure becomes:

```text
CD = 0.03276165 + 0.003889879358796229 = 0.03665152935879623
P_crank = 245.94 W
```

## Engineering Read

The old `174 W` number is optimistic once compared against the higher wing-drag
CFD-like result. But the correct statement is not simply "OpenFOAM says CD is
higher." The correct statement is:

- the definitions are different,
- induced drag must not be added again to OpenFOAM,
- and once the same non-wing reserve logic is restored on top of the higher wing
  CD, the implied screening crank power is far above `174 W`.
