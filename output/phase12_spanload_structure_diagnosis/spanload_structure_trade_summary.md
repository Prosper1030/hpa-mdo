# Spanload Structure Trade Summary

All variants are diagnostic 6 deg beam-line proxy runs through the canonical inverse-design wrapper with refresh_steps=0. Synthetic spanload rows are not new aerodynamic rankings.

- current_avl_actual_spanload: tube 77.01360725359352 kg, clearance 0.0651858601168413 m, root-bending ratio 1.0, P_crank estimate 178.08030381079178 W
- more_inboard_loaded_spanload: tube 14.702920907067146 kg, clearance 0.0064767260931653525 m, root-bending ratio 0.9367662620345778, P_crank estimate 183.79802295072994 W
- slightly_reduced_outer_loading: tube 77.01360725359352 kg, clearance 0.0651858601168413 m, root-bending ratio 0.9778195421588817, P_crank estimate 179.836914067535 W
- elliptical_like_spanload: tube 77.01360725359352 kg, clearance 0.0651858601168413 m, root-bending ratio 1.0298931343363322, P_crank estimate 176.62257169530386 W
- birdman_style_outboard_z_shape: tube 77.01360725359352 kg, clearance 0.0651858601168413 m, root-bending ratio 1.0, P_crank estimate 178.08030381079178 W

Answer:
- Shifting load inboard can reduce the bending proxy and, in this synthetic case, cuts tube mass from 77.0 kg to 14.7 kg. It still misses 11.5 kg and fails the 20 mm clearance threshold.
- A small outer-load reduction did not escape the 77 kg catalog wall in this MVP run; elliptical loading raised root bending and also stayed at 77 kg.
- The simple Birdman-style exponent-only z(y) test did not help; the useful next step is a control-station loaded-shape search plus wire/layout options, not just a scalar exponent.
- Under the current 34.3 m span, wire layout, and catalog search, 11.5 kg at 6 deg is unrealistic. That is not proof that 6 deg is physically impossible; it is proof that the current structural contract is not yet the right one.
