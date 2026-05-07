# Z Definition Check

For the smooth_tier2_production_baseline, the exported aerodynamic surface and the canonical beam-line target are close at the original low-Z state but are not the same object.

- Canonical inverse design uses the structural beam-line requested loaded shape: main-spar and rear-spar node Z.
- The HPA 6-7 deg guideline refers to the final loaded aerodynamic wing shape relative to root/centerline, ideally quarter-chord or an explicitly defined aerodynamic section reference.
- The Phase 11 sweep reports `effective_dihedral_deg = atan(target_main_tip_z_m / semi_span)`, which is a beam-line proxy. It is useful for controlled structural search but not fully equivalent to aerodynamic effective dihedral until the beam-to-aero-surface offset is frozen.
- Built-in geometric dihedral is included in the current exported aero surface `z_m`; the sweep is not elastic deflection added on top of that, it rescales the requested loaded beam-line Z state.

Key numbers are in `z_definition_check.csv`.
