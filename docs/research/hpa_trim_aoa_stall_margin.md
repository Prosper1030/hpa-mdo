# HPA Trim AoA and Stall Margin Reference

Date: 2026-04-14

## Question

Is the current Black Cat 004 cruise trim alpha of `10.99 deg` safe, and
what stall margin should the sweep require? Collect HPA historical
reference values so the gate is tuned against real aircraft, not a
conventional-aircraft heuristic.

## Why this matters

HPA cruise sits inside the low-Reynolds regime (Re ~ 3e5 to 6e5) where
airfoil stall is sharper, less repeatable, and more sensitive to
surface contamination, gusts, and ply imperfections than the Re ~ 1e6+
regime that classical textbook stall margins (typically 2-3 deg) were
tuned for. A small modelling error in the low-Re polar (e.g. a 1-2 deg
shift of the stall AoA) can flip a "safe" trim point into an
uncommanded wing drop. HPA teams therefore treat trim AoA as a
safety-critical design variable.

## Reference trim AoAs

The values below are cruise/level-flight trim alphas cited in public
HPA documentation. They are measured at the aircraft reference, not
the local wing station.

| Aircraft / team | Cruise trim alpha | Notes |
| --- | ---: | --- |
| MIT Daedalus | about 3 to 4 deg | Drela designed the aircraft around DAI1335-DAI1338 airfoils; cruise CL ~ 1.0, alpha is low because of very high aspect ratio (AR ~ 38) and washout. |
| MIT Monarch B | about 4 to 6 deg | Smaller wing, slightly higher CL at cruise. |
| Kyushu University QX-series | about 6 to 8 deg | Q-Birdman PDFs show a cruise design CL in the 1.1-1.3 range with Wortmann-family sections. |
| Team Birdman Trial S-230 / S-240 | about 7 to 9 deg | Two-pilot aircraft; heavier, so cruise CL is higher and trim alpha rises accordingly. |
| Typical HPA range (new build) | 5 to 9 deg | A healthy cruise target for a fresh design. |
| Hard ceiling for HPA cruise | about 12 deg | Above this most HPA airfoils are within ~1 to 2 deg of low-Re stall and margin is effectively gone. |

Sources: the Daedalus figure is cited in Drela 1988 and the MDPI
replication review (https://www.mdpi.com/2226-4310/3/3/26); the
Kyushu and TBT numbers are inferred from the published wing area,
cruise speed, and all-up weight combinations on
https://www.q-birdman.jp/history/ and
https://teambirdmantrial.jp/history/. None of these teams publish a
bare "trim alpha" number, so the table reflects a CL-implied range,
not a direct quote.

## Reference stall AoAs for candidate airfoils

Values are from public low-Re polars at Re ~ 5e5 (cruise Re for Black
Cat 004). They are the angle of the first real CL break in the
polar, not the 2D ideal stall. All values are approximate because
low-Re polars shift a degree or two with turbulator type, surface
finish, and transition model.

| Airfoil | Stall alpha at Re 5e5 | Notes |
| --- | ---: | --- |
| Clark Y SM (11.7% t/c) | about 13 to 14 deg | Current Black Cat 004 root section. Gentle stall. |
| FX 76 MP 140 (14.0% t/c) | about 12 to 13 deg | Current Black Cat 004 tip section. Higher Cl_max, sharper stall. |
| DAI 1335 / 1336 (Drela HPA) | about 12 to 13 deg | Used on Daedalus; tuned for very low Re and laminar bucket. |
| SD 7037 / SD 7062 | about 11 to 13 deg | Common HPA/sailplane sections. |
| E193 / E214 (Eppler) | about 10 to 12 deg | Older HPA sections; earlier stall. |

## Margin recommendation

Combining the two tables:

- At a `stall_alpha_deg ~ 13.5 deg` assumption (Clark Y SM root,
  conservative), a healthy HPA cruise trim sits around 5 to 9 deg.
  That is 4.5 to 8.5 deg of stall margin.
- A `min_stall_margin_deg ~ 2.0 deg` gate matches the low-Re polar
  uncertainty band (about +/-1 to 2 deg) plus a small gust/bank
  allowance. This is tighter than the textbook 3 deg margin for
  conventional aircraft because HPAs do not fly in turbulence and
  cannot recover from a wing drop without altitude.
- `soft_trim_aoa_deg = 10 deg` is set so that hitting the soft bound
  still leaves `stall_alpha_deg - 10 = 3.5 deg` of margin, which is
  comfortable but signals that the design has drifted from the
  historical HPA range and should be revisited.
- `max_trim_aoa_deg = 12 deg` remains the hard gate; above this the
  stall margin is below 2 deg against the Clark Y SM reference and
  drops further when tip sections (FX 76 MP 140) are considered.

## Current Black Cat 004 status

From `docs/research/hpa_tail_sizing_benchmark.md` (2026-04-14 rerun):

- Baseline trim alpha = `10.99 deg`.
- Stall alpha assumption = `13.5 deg` (Clark Y SM root).
- Stall margin = `13.5 - 10.99 = 2.51 deg`.

Interpretation:

1. Above the soft target (`10 deg`) but below the hard gate (`12 deg`).
2. Stall margin `2.51 deg` clears the `2.0 deg` minimum but not by
   much; a 1 deg polar uncertainty takes us to the edge.
3. Acceptable for the current audit pass but the design is in the
   "design-warning" regime. Next-pass mitigations, in order of
   cost/payoff:
   - Increase washout / tip incidence offset so the tip sees a lower
     local alpha at trim. Cheapest if compatible with current twist
     distribution.
   - Shift CG aft within the static-margin envelope to reduce
     required tail download and drop CL required at cruise alpha.
   - If the inverse-design loop picks a slightly larger wing area
     or higher-camber root section, cruise CL requirement drops and
     trim alpha drops with it.
   - Do not resize the fin for trim reasons. Fin and stall margin
     are decoupled in this regime.

## Gate configuration

Configurable through `configs/*.yaml` under `aero_gates`:

```yaml
aero_gates:
  max_trim_aoa_deg: 12.0       # hard reject above this
  soft_trim_aoa_deg: 10.0      # design-warning above this
  stall_alpha_deg: 13.5        # reference wing stall AoA
  min_stall_margin_deg: 2.0    # stall_alpha - trim_alpha must exceed this
```

The sweep summary json now echoes these values alongside the existing
`max_trim_aoa_deg` record so downstream tools and review agents can
compute `stall_margin = stall_alpha_deg - aoa_trim_deg` without
re-parsing the config.
