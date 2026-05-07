# Phase 9 Structure Number Derivation

This file explains the three reported smooth production baseline numbers:

- `tip_deflection_estimate_m = 2.285692439569747`
- `jig_tip_z_unloaded_estimate_m = -1.235110795569747`
- `selected_tube_product = CF-STD-100x98`, `selected_tube_estimated_full_span_tube_mass_kg = 32.95899456`

The persisted result is in:

- `output/final_candidate_validation/smooth_tier2_production_baseline/structure_jig_audit.csv`

## 1. Tip Deflection = 2.286 m

The reported tip deflection is a scaled concept proxy, not a structural solve.

Code path:

- `scripts/validate_smooth_tier2_production_baseline.py:551` calls `structure_jig_audit()`.
- `structure_jig_audit()` calls `phase9.spanload_structure_metrics()` and `phase9.structure_jig_row()` at lines `563-584`.
- `phase9.structure_jig_row()` calls `nominal_jig_estimate()` at `scripts/phase9_structure_jig_smooth_planform.py:789`.
- `nominal_jig_estimate()` calls `estimate_tip_deflection()` at lines `757-762`.

The nominal model inputs are hard-coded in `nominal_jig_estimate()`:

- gross mass: `98.5 kg`
- span: `34.332286 m`
- half span: `17.166143 m`
- root tube OD: `0.070 m`
- tip tube OD: `0.040 m`
- root wall: `0.0007 m`
- tip wall: `0.0005 m`
- tube count: `2` spars per wing, `2` wings
- Young's modulus: `120e9 Pa`
- spar vertical separation: `0.10 m`
- taper correction factor: `1.7`
- lift-wire relief enabled
- lift-wire attach span fraction: `0.70`
- lift-wire cruise lift fraction carried: `0.35`

The scalar model in `src/hpa_mdo/concept/jig_shape.py:28-111` computes:

- `distributed_load = gross_mass * g / (num_wings * half_span)`
- root thin-wall tube inertia per tube: `pi * D^3 * t / 8`
- aggregate per-wing inertia: `num_spars * inertia_per_tube + num_spars * area_per_tube * (separation / 2)^2`
- `EI = E * aggregate_inertia`
- unbraced cantilever tip deflection: `w * L^4 / (8 * EI) * taper_factor`
- lift-wire relief: `R * a^2 * (3L - a) / (6 * EI) * taper_factor`
- wire-relieved deflection: `max(0, unbraced - relief)`

For the baseline span and hard-coded proxy tube:

- nominal wire-relieved tip deflection: `2.1403110217338916 m`
- nominal unbraced tip deflection: `4.514789105049692 m`
- nominal wire relief effect: `2.3744780833158003 m`

Then `structure_jig_row()` scales that nominal deflection by the ratio of AVL spanload second-moment proxies:

- current smooth baseline `integral(y^2 * L'(y) dy) = 35341.32270601469`
- old FX/Clark raw reference `integral(y^2 * L'(y) dy) = 33093.43864504187`
- scale ratio = `35341.32270601469 / 33093.43864504187 = 1.0679253698923066`

Therefore:

- `tip_deflection_estimate_m = 2.1403110217338916 * 1.0679253698923066 = 2.285692439569747 m`
- `unbraced_tip_deflection_estimate_m = 4.514789105049692 * 1.0679253698923066 = 4.821457824995948 m`
- `wire_relief_effect_m = 2.3744780833158003 * 1.0679253698923066 = 2.5357653854262012 m`

Engineering interpretation: this is a load-shape-scaled uniform cantilever estimate. It is useful as a warning flag, but it is not a beam finite-element result.

## 2. Unloaded Jig Tip Estimate = -1.235 m

This number is a one-line scalar subtraction in `structure_jig_row()`:

- `effective_dihedral_loaded_deg = atan2(loaded_tip_z, half_span)`
- `jig_tip_z_unloaded_estimate_m = loaded_tip_z_m - tip_deflection_estimate_m`

For the smooth production baseline:

- loaded tip z: `1.050581644 m`
- proxy tip deflection: `2.285692439569747 m`

Therefore:

- `jig_tip_z_unloaded_estimate_m = 1.050581644 - 2.285692439569747 = -1.235110795569747 m`

Engineering interpretation: this is not a recovered unloaded jig axis. It says that, under this proxy, a scalar deflection subtraction would place the unloaded tip below the reference floor. The actual dual-beam inverse-jig solver could distribute prebend, rear-spar twist, wire support, and clearance constraints differently.

## 3. CF-STD-100x98 = 32.959 kg

The carbon tube selection is also a proxy.

Code path:

- `structure_jig_audit()` computes current EI at `scripts/validate_smooth_tier2_production_baseline.py:585-592`.
- It computes required EI via `phase9.required_ei_from_deflection()` at lines `595-599`.
- It calls `phase9.carbon_tube_candidates()` at lines `600-608`.
- `carbon_tube_candidates()` reads `data/carbon_tubes.csv` and sorts by `(not ei_pass, estimated_full_span_tube_mass_kg)` at `scripts/phase9_structure_jig_smooth_planform.py:860-906`.

The current proxy EI is computed with:

- OD: `0.070 m`
- ID: `0.070 - 2 * 0.0007 = 0.0686 m`
- Young's modulus: `120e9 Pa`
- tube count per wing: `2`
- vertical separation: `0.10 m`

Formula in `tube_ei_nm2()`:

- tube area: `pi * (OD^2 - ID^2) / 4`
- tube centroid inertia: `pi * (OD^4 - ID^4) / 64`
- aggregate inertia: `tube_count * (tube_inertia + tube_area * (vertical_separation / 2)^2)`
- `EI = E * aggregate_inertia`

Current proxy EI:

- `113398.22720164707 N*m^2`

Required EI uses a linear deflection scaling:

- target tip deflection = `max(loaded_tip_z_m, 0.25) = 1.050581644 m`
- current tip deflection = `2.285692439569747 m`
- current EI = `113398.22720164707 N*m^2`
- required EI = `current_EI * current_tip_deflection / target_tip_deflection`
- required EI = `246714.25781680338 N*m^2`

The selected catalog row is:

- product: `CF-STD-100x98`
- OD: `100 mm`
- ID: `98 mm`
- wall: `1 mm`
- mass per meter: `0.480 kg/m`

Its proxy EI is:

- `278068.46045898093 N*m^2`

That passes the required EI proxy:

- `278068.46045898093 >= 246714.25781680338`

Mass formula in `carbon_tube_candidates()`:

- `estimated_full_span_tube_mass_kg = 2 * half_span * tube_count_per_wing * mass_per_meter`
- `= 2 * 17.166143 * 2 * 0.480`
- `= 32.95899456 kg`

## What 32.959 kg Means

`32.95899456 kg` means:

- carbon tube mass only
- both left and right half-wings
- two catalog tubes per wing half
- constant `CF-STD-100x98` tube along the whole span in this proxy

It does **not** mean:

- one spar only
- one half-wing only
- a completed spar system
- total wing structural mass
- total aircraft structural mass
- a sized dual-beam main/rear spar system

It excludes:

- joints
- rib attachments
- ribs
- skins
- wires
- wire fittings and terminals
- bonded inserts
- sleeves
- local reinforcement
- spar caps/layup tailoring
- adhesive and hardware
- strength, buckling, ovalization, crippling, and joint knockdowns

Engineering concern: `carbon_tube_candidates()` passes `youngs_pa=120e9` to every catalog row. It does not use `material_key` to vary modulus between `carbon_fiber_hm` and `carbon_fiber_std`. The selected `CF-STD-100x98` is therefore a mass/EI proxy result, not a material-grade catalog sizing decision.
