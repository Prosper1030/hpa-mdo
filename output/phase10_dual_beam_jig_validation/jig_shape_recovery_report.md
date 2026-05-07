# Jig Shape Recovery Report

## Did The Real Model Run?

Yes. `run_dual_beam_mainline_kernel(mode=dual_beam_production, link_mode=joint_only_offset_rigid)` ran through the real dual-beam / explicit wire-truss path for the smooth baseline and old FX/Clark baseline.

## Smooth Baseline, Proxy-Selected Tube Recipe

- tip deflection, main spar: `0.378 m`
- tip deflection, rear spar: `0.371 m`
- loaded tip z: `1.051 m`
- recovered unloaded jig tip z, main spar: `0.672 m`
- recovered unloaded jig minimum z: `-0.000 m`
- loaded-shape main-z RMS error: `0.000000 m`
- loaded-shape twist RMS error: `0.000000 deg`
- geometry validity passed: `False`
- numerical consistency passed: `False`
- hard failures: `geometry_validity|moment_closure`
- moment-closure residual: `263.423 N*m`
- inverse-jig failures: `geometry_validity`

The zero loaded-shape error is expected for the frozen-load inverse method: it algebraically backs out `jig = target_loaded_shape - solved_displacement`, then re-adds the same displacement field. This validates the adapter plumbing, not a coupled aeroelastic convergence loop.
