# Structure Number And Branch Derivation

## Mass Definition

The reported `tube_mass_kg` in the z-state sweep maps to `production.recovery.spar_tube_mass_full_kg` from `dual_beam_mainline.recovery`. The recovery code computes half-wing tube mass as the spanwise sum of `(main_mass_per_length + rear_mass_per_length) * element_length`, then doubles it for full span. `total_structural_mass_kg` adds joint/fitting mass and is also full-span.

This means the z-state sweep mass is:

- full-span main plus rear carbon tube mass for both half-wings;
- not a single spar;
- not just one half-wing;
- not including ribs, external wire mass, joints beyond the configured joint/fitting masses, fittings beyond that simple term, adhesives, or manufacturing scrap.

## Reconstructed Tube Mass Check

Using `carbon_fiber_hm` density = 1600 kg/m3 and the selected segment radius/wall arrays:

| case | reported tube mass | reconstructed tube mass | residual |
|---|---:|---:|---:|
| 2.000 m heavy branch | 77.014 kg | 77.194 kg | -0.181 kg |
| 2.025 m light branch | 15.519 kg | 15.513 kg | 0.006 kg |
| 2.700 m light branch | 11.595 kg | 11.603 kg | -0.008 kg |

The mass arithmetic is therefore internally consistent enough for diagnosis. The suspicious part is the selected branch, not the summation.

## Branch Evidence

- Heavy branch at 2.000 m: main walls `[8,8,8,8,8,8]` mm and rear walls `[8,8,8,8,8,8]` mm; reduced variables at `wall_thickness_fraction=1.0`.
- Light branch at 2.025 m: main walls `[0.8,0.8,0.8,0.8,0.8,0.8]` mm and rear outboard step `[0.8,0.8,0.8,0.8,3.8,3.8]` mm; reduced variables at `wall_thickness_fraction=0.0` and large-radius bounds.
- First light branch clearance is only 0.0003 m; below that, the light branch would likely violate jig clearance.

## Side-by-side Load Ownership Evidence

At approximately 6 deg beam-line target:

| load ownership | tube mass | clearance | tip deflection proxy | wire tension |
|---|---:|---:|---:|---:|
| current AVL actual spanload | 77.014 kg | 0.0652 m | -0.102 m | 256.2 N |
| synthetic more-inboard spanload | 14.703 kg | 0.0065 m | 0.863 m | 2614.6 N |

The mass cliff is therefore coupled to load ownership/spanload, not only to target tip Z.
