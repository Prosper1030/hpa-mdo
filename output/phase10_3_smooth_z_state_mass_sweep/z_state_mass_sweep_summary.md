# Smooth Baseline Z-State Mass Sweep

This diagnostic holds the smooth Tier2 production planform and AVL spanload fixed, then varies the requested loaded beam-line Z state. The reported threshold is based on actual target spar-tip Z coordinates; the scale column is only the generator knob used by the canonical script.

- spar tube mass line: 11.7534 kg
- aero source: candidate_avl_spanwise from smooth_tier2_production_baseline
- structural search: canonical direct_dual_beam_inverse_design.py, refresh_steps=0, skip_local_refine, skip_step_export, limited_zonewise ribs, no ground-clearance recovery
- z-state source of truth: selected.target_loaded_shape in each summary JSON; the per-case target_loaded_shape_spar_data.csv export is retained as a legacy artifact and may show the unscaled base geometry in this diagnostic

First sampled pass of the 11.7534 kg spar-tube line:
- target main tip z: 2.650 m
- target rear tip z: 2.635 m
- tube mass: 11.595 kg
- total structural mass: 14.095 kg
- jig clearance min: 1.5 mm
- max jig prebend: 2.363 m
- equivalent tip deflection: 1.635 m

First sampled pass with at least 10 mm jig clearance:
- target main tip z: 2.675 m
- tube mass: 11.595 kg
- jig clearance min: 14.5 mm

First sampled pass with at least 20 mm jig clearance:
- target main tip z: 2.700 m
- tube mass: 11.595 kg
- jig clearance min: 27.5 mm

Lightest sampled state:
- target main tip z: 4.250 m
- tube mass: 9.689 kg
- selected main wall mm: [0.8,0.8,0.8,0.8,0.8,0.8]
- selected rear wall mm: [0.8,0.8,0.8,0.8,0.8,0.8]

Engineering read:
- The previous high-mass smooth result was not a proof that the new design is structurally heavy; it was a low-Z requested-shape state.
- Passing the old spar-tube mass line requires enough requested loaded Z for the inverse jig to accept larger elastic recovery while maintaining clearance and manufacturing limits.
- These rows are still a diagnostic sweep, not a final structural gate change.
