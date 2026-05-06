# VSPAERO CDo Warning

- Do not compare VSPAERO `.polar` `CDo` or `CDtot` directly against the Phase 6/7 mission profile drag budget.
- In this diagnostic run, VSPAERO thin/VLM wrote internal `CDo`, `CDi`, and `CDtot` columns, but the run did not load or trace the reusable full-alpha/XFOIL profile polar database.
- The sidecar mission profile drag remains the full-polar/XFOIL database estimate: Policy A profile_cd about 0.010995 and Policy C profile_cd about 0.011398 from the Phase 7 reports.
- Use VSPAERO here for lift-curve, induced-drag, reference, and spanload parity only unless a separate, traced viscous/profile model is wired into VSPAERO.
