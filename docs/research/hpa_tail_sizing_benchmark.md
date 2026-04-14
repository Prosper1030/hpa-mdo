# HPA Tail Sizing Benchmark

Date: 2026-04-14

## Question

Check whether the Black Cat 004 AVL vertical fin is genuinely undersized, or whether the low rudder authority finding came from a modeling/unit interpretation issue.

## External Benchmarks

| Aircraft / team | Wing area | Span | Vertical tail area | Vertical tail arm / Vv | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| Kyushu University QX-07 | 19.1 m2 | 24.6 m | 0.92 m2 | Vv 0.008 | Q-birdman PDF lists the principal dimensions directly. |
| Kyushu University QX-17 | 18.3 m2 | 27.0 m | 0.600 m2 | Vv 0.00437 | Q-birdman PDF lists the principal dimensions directly. |
| Kyushu University QX-18 | 18.0 m2 | 25.2 m | 0.574 m2 | Vv 0.00437 | Q-birdman PDF lists the principal dimensions directly. |
| Team Birdman Trial S-230 Cygnus | 49.7 m2 | 38.0 m | 3.71 m2 | 7.20 m / Vv 0.0141 | Two-pilot aircraft; much larger payload and wing. |
| Team Birdman Trial S-240 Iris | 49.85 m2 | 39.0 m | 3.77 m2 | 7.10 m / Vv 0.0138 | Two-pilot aircraft; much larger payload and wing. |
| MIT Daedalus | 30.8 m2 | 34.1 m | about 1.4-1.8 m2 | about 6.1 m / Vv about 0.008-0.010 | Public drawing does not tabulate tail area; this is a drawing-scale estimate. |

Sources:

- Kyushu University QX-07 PDF: https://www.q-birdman.jp/history/images/qx-07.pdf
- Kyushu University QX-17 PDF: https://www.q-birdman.jp/history/images/qx-17.pdf
- Kyushu University QX-18 PDF: https://www.q-birdman.jp/history/images/qx-18.pdf
- Team Birdman Trial S-230 Cygnus: https://teambirdmantrial.jp/history/s-230-cygnus/
- Team Birdman Trial S-240 Iris: https://teambirdmantrial.jp/history/s-240-iris/
- MIT Daedalus drawing: https://web.mit.edu/drela/Public/web/hpa/daedalus.pdf
- MDPI Daedalus replication summary: https://www.mdpi.com/2226-4310/3/3/26

## Black Cat 004 Check

From `data/blackcat_004_full.avl`:

- Sref = 30.69 m2
- Bref = 33.0 m
- Xref = 0.251460573 m
- Fin x = 5.0 m
- Fin span = 2.4 m
- Fin chord = 0.7 m
- Sfin = 1.68 m2
- Lfin = 4.748539427 m

So:

`Vv = Sfin * Lfin / (Sref * Bref) = 0.00788`

That is not in the Team Birdman Trial two-pilot range, but it is in the Kyushu single-pilot / Daedalus-like range. A 4-5 m2 fin would imply `Vv ~0.019-0.023`, which is closer to conventional-aircraft tail-volume heuristics than to the HPA examples above.

If we later choose a TBT-like `Vv ~0.014` target while keeping the current tail arm, the corresponding fin area is:

`Sfin_target = 0.014 * Sref * Bref / Lfin = 2.99 m2`

So the first design step would be closer to 3.0 m2, not 4-5 m2.

## AVL Modeling Findings

- The main-wing-to-fin distance is not being read short. Current AVL reference and fin x-location give `Lfin = 4.75 m`, matching the handoff estimate.
- The `IYsym=0` and `YDUPLICATE` pattern is correct for lateral/directional derivatives: wing and horizontal tail are duplicated; the centerline vertical fin is not duplicated.
- `Xhinge=0.0` is acceptable for the all-moving tail use case. The archived AVL manual at `docs/Manual/avl_doc.txt` describes `CONTROL` gain as degrees of deflection per control variable and supports whole-chord controls.
- AVL reports control derivatives with respect to the control variable. With the current control gain, `Cnd02 = 0.000486` is per degree, not per radian. Interpreting it as `/rad` underestimates rudder authority by about 57.3x.

At cruise:

- q = 25.878 Pa
- q * Sref * Bref = 26,202 N m
- Cnd02 = 0.000486 / deg = 0.0278 / rad
- 3 deg rudder gives `Cn ~= 0.00146`
- yaw moment from 3 deg rudder is about `38 N m`

That is still modest, but it is not the sub-1 N m result from the earlier unit interpretation.

## Baseline Stability Snapshot

Re-running the current `data/blackcat_004_full.avl` baseline on 2026-04-14 gives:

- Dutch roll mode: found, real = -0.215666, imag = 0.549299, status = stable.
- Spiral mode: real = -0.001998, stable with time-to-half about 347 s.
- Beta sweep: trimmed through 12 deg, `Cn_beta = -0.0242 / rad`, `Cl_beta = -0.135 / rad`.
- Trim: `CL = 1.235`, alpha = 10.99 deg, `CDind = 0.0173`, span efficiency = 0.638.
- Rudder derivative: `Cnd02 = 0.000486 / deg`, coupling parse status = ok.

Interpretation: lateral/directional stability is acceptable for the current AVL audit. The two items to keep watching are the high trim alpha and the still-modest rudder authority.

## Trim Alpha Interpretation

The current baseline trim alpha is `10.99 deg`. That is below the active `max_trim_aoa_deg = 12.0 deg` hard gate, so it is not a current stability-gate failure. It is still high for a cruise design point because it leaves limited margin for low-Re airfoil polar error, local separation, gusts, and flexible-wing incidence changes.

Use the following working targets until the airfoil polar/stall model is refreshed:

- Hard gate: keep `max_trim_aoa_deg = 12.0 deg` for sweep compatibility and to avoid overreacting to AVL-only induced-drag modeling.
- Soft design target: prefer baseline/cruise trim alpha at or below about `10 deg`.
- Healthy cruise target: aim for about `8-9 deg` if the wing incidence, tail trim, or loading trade can achieve it without a mass/control penalty.

So the current `10.99 deg` result is acceptable for continuing the pipeline, but it should be treated as a design-warning item rather than a comfortable final cruise point.

## OpenVSP Geometry Status

The local machine currently does not have the `openvsp` Python module, so the builder cannot directly write a `.vsp3` file here through the OpenVSP API. The VSP fallback has been expanded to generate a full-aircraft `.vspscript` with `MainWing`, `Elevator`, and `Fin` geometry from `configs/blackcat_004.yaml`.

Generated visual script:

`output/blackcat_004_visual/blackcat_004_full_aircraft.vspscript`

Because `output/` is ignored, that generated script is not committed. To create the corresponding prettier `.vsp3`, run the script in the OpenVSP GUI or rerun `VSPBuilder.build_vsp3(...)` in an environment where the OpenVSP Python bindings are installed.

## Decision

Do not resize the fin in this pass. Keep `Sfin = 1.68 m2`, fix the AVL exporter so regenerated models preserve the explicit vertical rudder hinge axis, and treat future fin growth as a design trade:

- Daedalus/Kyushu-like target: keep about 1.7-2.1 m2.
- TBT-like two-pilot target: test about 3.0 m2.
- Conventional-aircraft target: 4-5 m2, but this is not supported by the HPA comparison alone.
