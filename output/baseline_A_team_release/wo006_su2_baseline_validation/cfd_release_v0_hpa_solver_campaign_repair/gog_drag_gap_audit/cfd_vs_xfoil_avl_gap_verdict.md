# CFD vs XFOIL+AVL Gap Verdict

## Question

Accepted Fine OpenFOAM:

```text
CL_primary = 1.160934
CD_total_physical = 0.03326556
```

Old wing-only XFOIL+AVL:

```text
CD_wing_old = XFOIL clean profile + AVL induced
            = 0.009368851 + 0.012761300
            = 0.022130151
```

Gap:

```text
0.03326556 - 0.022130151 = 0.011135409
0.011135409 / 0.022130151 = 50.32%
```

## Main findings

1. The gap is not primarily an induced-drag bookkeeping problem.
   - AVL induced drag is internally consistent.
   - OpenFOAM total drag already contains induced drag.
   - Adding AVL `CDi` to OpenFOAM would double-count induced drag.

2. The old `0.0221` is a clean-transition wing-only number.
   - It excludes the old non-wing reserve.
   - Its profile term is clean XFOIL, defaulting to `Ncrit=9`, `xtrip=(1.0,1.0)`.
   - Several outboard clean profile `cd` values are extremely low and should not be treated as rough or fully turbulent drag.

3. The existing rough XFOIL bracket is enough to make the 50% gap physically plausible.
   - Existing clean profile integration: `0.009368851`
   - Existing rough profile integration: `0.023487768`
   - Rough XFOIL + AVL induced wing-only: `0.036249068`
   - Current SA OpenFOAM wing physical: `0.03326556`

4. The CFD result is still not automatically design-truth.
   - CFD pressure drag is `0.02295001`.
   - After estimated induced drag, pressure/form residual remains about `0.01035`.
   - The accepted artifacts do not include spanwise or upper/lower drag decomposition.
   - Grid independence does not validate the turbulence/transition formulation.

## Verdict classification

Formal verdict: unresolved.

Best engineering read:

- The old clean XFOIL+AVL value is likely underpredicting drag if the real wing or the CFD model should be treated as early-transition, rough, or fully turbulent.
- The current OpenFOAM SA value may be a plausible fully turbulent/rough-side value, but it may overpredict a smooth clean HPA mission condition.
- The dominant uncertainty is transition/profile/form drag, not induced drag.

So the current evidence does not support replacing the old power estimate with `CD=0.03326556` yet.

## Can OpenFOAM `CD=0.0333` replace the old power estimate now?

No.

Use it as a CFD reference and a high-drag warning, not as the design-power replacement. It is grid-independent enough within the accepted Fine/Medium family, but not formulation-independent enough. The SA/no-transition physics basis must be checked before power is updated.

## Next single diagnostic action

Run one fixed-mesh transition/turbulence sensitivity on the accepted Fine mesh. Do not run a new grid refinement.

Minimum diagnostic contract:

- same Fine mesh;
- same AoA and reference geometry;
- same force groups and `total_physical` definition;
- transition-capable SST if locally available; otherwise a bounded laminar/SST or laminar/SA bracket;
- same final-window stability checks;
- report `CL_primary`, `CD_total_physical`, pressure/viscous split, and any force-window drift;
- compare against clean XFOIL+AVL `0.02213015`, rough XFOIL+AVL `0.03624907`, and SA OpenFOAM `0.03326556`.

Decision rule:

- If transition/laminar sensitivity moves CD toward the clean old value, current SA is probably overpredicting clean-mission drag.
- If transition/SST stays near current SA, old clean XFOIL+AVL is probably underpredicting operational wing drag.
- If the pressure residual stays large without localization, add spanwise and upper/lower force decomposition before any design-power update.
