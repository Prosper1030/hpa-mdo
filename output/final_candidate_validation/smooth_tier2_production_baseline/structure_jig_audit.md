# Structure / Jig Audit

Generated: 2026-05-07T05:23:43.375355Z

- `root_bending_proxy_n_m`: 3544.979541022861
- `tip_deflection_estimate_m`: 2.285692439569747
- `loaded_tip_z_m`: 1.050581644
- `jig_tip_z_unloaded_estimate_m`: -1.235110795569747
- `jig_feasibility_band`: `proxy_warning`
- `selected_tube_product`: `CF-STD-100x98`
- `selected_tube_estimated_full_span_tube_mass_kg`: 32.95899456
- `current_spar_tube_mass_target_kg`: 11.7534
- `structure_proxy_pass`: False
- `failure_modes`: `jig_shape_driven|stiffness_mass_target_driven|strength_not_evaluated_proxy`

Engineering read: the proxy failure is stiffness/jig-shape driven. The catalog tube that first meets the EI proxy is far above the current spar tube mass target, and the scaled jig estimate still drives the unloaded tip below zero. This run does not evaluate laminate strength or buckling, so do not call it strength-pass.
