# Spanload Definition

- `y_m`: half-wing spanwise coordinate in meters, root to tip.
- `eta`: normalized half-span coordinate, `eta = y_m / (span_m / 2)`, root 0 and tip 1.
- `theta_rad`: lifting-line coordinate `theta = acos(eta)`, root `pi/2` and tip 0.
- `Lprime_Npm`: local lift per unit span from AVL or derived strip loading.
- `cl_times_c`: local section `Cl * chord_m`, used only as a shape proxy when circulation is unavailable.
- `Gamma_m2ps`: circulation proxy. When available, the fit uses `Gamma = 2 * span_m * V * sum(A_n sin(n theta))`.
- Legacy exported `avl_circulation` rows from `station_table.csv` are `Cl * chord_m`; MVP 1 converts them to `Gamma_m2ps` with `0.5 * V_mps * Cl * chord_m` before fitting.
- `normalized_loading`: positive loading divided by its half-span integral for target-vs-AVL shape comparison.
- Negative loading, if present, is preserved in Fourier coefficient fitting and clipped only for positive lift-fraction diagnostics.
- Half-span convention: CSV rows are root-to-tip half-wing rows. Full-wing lift is twice the half-wing integral when needed.
- Trust label: MVP 1 calibration is diagnostic only; it does not change production ranking, gates, optimizers, or structure truth.
