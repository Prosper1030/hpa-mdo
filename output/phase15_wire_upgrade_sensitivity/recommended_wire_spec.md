# Recommended Wire Spec

## Recommendation

Use `6 kN modeled allowable` as the first upgrade target. Under the current local safety policy, that means a published minimum breaking load of at least `22.5 kN`, before any loss from knots, bends, splices, UV, abrasion, creep, or fittings.

For a more robust next build, target `8 kN modeled allowable` if the drag, attach fitting, and packaging penalty are acceptable. That requires a published minimum breaking load of at least `30.0 kN` under the same policy. A `10 kN` modeled allowable requires about `37.5 kN` MBL and should be treated as a larger hardware redesign item, not a simple cord swap.

## Market Check

| supplier | product | diameter mm | strength type | break load kN | source note |
| --- | --- | ---: | --- | ---: | --- |
| Marlow | [D12 75/78](https://shop.marlowropes.com/content/files/datasheets/defence/datasheets%20with%20iso%2014001/d12%2075%20and%2078%20%20datasheet%202024%20correct.pdf) | 2.5 | minimum | 4.8 | PDF table line gives 2.5 mm minimum strength 4.8 kN. |
| Marlow | [D12 75/78](https://shop.marlowropes.com/content/files/datasheets/defence/datasheets%20with%20iso%2014001/d12%2075%20and%2078%20%20datasheet%202024%20correct.pdf) | 4.0 | minimum | 18.1 | PDF table line gives 4 mm minimum strength 18.1 kN. |
| Marlow | [D12 75/78](https://shop.marlowropes.com/content/files/datasheets/defence/datasheets%20with%20iso%2014001/d12%2075%20and%2078%20%20datasheet%202024%20correct.pdf) | 6.0 | minimum | 30.8 | PDF table line gives 6 mm minimum strength 30.8 kN. |
| Marlow | [Excel D12 Max 78](https://shop.marlowropes.com/excel-d12-max-78-2-5mm-black-100mr-tv0006) | 2.5 | minimum | 9.2 | Product page lists 2.5 mm minimum break load 935 kg. |
| Premiumropes | [DX Core 78](https://www.premiumropes.com/dx-core-78) | 5.0 | catalog | 23.5 | Product page lists 5 mm strength 2400 kg. |
| Premiumropes | [DX Core 78](https://www.premiumropes.com/dx-core-78) | 6.0 | catalog | 31.3 | Product page lists 6 mm strength 3190 kg. |
| Samson | [AmSteel-Blue](https://www.samsonrope.com/docs/default-source/brochures/rm_line_selection_guide_web.pdf?Status=Temp&sfvrsn=5f36249d_4) | 5.0 | approx_average | 24.0 | Line selection guide lists 3/16 in / 5 mm average breaking strength 5400 lb. |
| Samson | [AmSteel-Blue](https://www.samsonrope.com/docs/default-source/brochures/rm_line_selection_guide_web.pdf?Status=Temp&sfvrsn=5f36249d_4) | 6.0 | approx_average | 38.3 | Line selection guide lists 1/4 in / 6 mm average breaking strength 8600 lb. |

## Spec Boundary

- Do not buy by nominal diameter alone. The same 2.5 mm class can be far below the current model-derived implied break load.
- Current artifact allowable `4.581 kN` implies `17.2 kN` minimum break under the local policy.
- For the next validation build, prefer a catalog line with published minimum breaking load, certified batch data if possible, spliced/thimbled end terminations, and explicit bend-radius and creep limits.
- Avoid knots in the primary load path. Treat every termination, pin bend, and clamp as a strength reducer until tested.
- Re-enter the final selected line as actual area, Young's modulus, pretension, and allowable, then rerun the candidate FEM load-factor package. Higher stiffness can move loads into the root and attach details.

## Practical Pick

- Minimum practical upgrade: a Dyneema/HMPE line whose published minimum break is at least `22.5 kN` for the `6 kN` allowable case.
- Preferred validation target: published minimum break at least `30 kN` for the `8 kN` allowable case, because it makes the 3.0G wire utilization comfortable while keeping a clear paper trail.
- The attach fitting and rib load-transfer check are now the gating engineering items; the market wire itself is not the blocker.
