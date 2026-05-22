# Final HPA Grid-Independence Verdict

Verdict: `medium_fine_grid_independence_demonstrated_for_locked_OpenFOAM_wing_drag`

Operating-condition lock:

The Coarse, Medium, and Fine rungs preserved `rhoInf=1.225`, `nu=1.4607e-05`, `V=6.5 m/s`, `AoA=0.18 deg`, `Sref=33.420059598 m^2`, `Cref=1.003721543 m`, `RAS/SpalartAllmaras`, matching drag/lift directions, artificial closure treatment, and the same `primary` / `total_physical` force definitions. No design power value was changed.

1. Did Medium pass force-window stability?
   Yes. Medium passed at 2000 iterations: CD_total drift `0.583%`, CD_primary drift `0.575%`, CL_primary drift `0.398%`, CmPitch drift `0.475%`.

2. Did Fine pass force-window stability?
   Yes. Fine passed at 2000 iterations: CD_total drift `0.524%`, CD_primary drift `0.518%`, CL_primary drift `0.326%`, CmPitch drift `0.409%`.

3. What are Coarse/Medium/Fine CL and CD?

   | grid | CL_primary | CD_primary | CD_total_physical |
   |---|---:|---:|---:|
   | Coarse | 1.159865 | 0.03565319 | 0.03571427 |
   | Medium | 1.158639 | 0.03369494 | 0.03375281 |
   | Fine | 1.160934 | 0.03320877 | 0.03326556 |

4. Is CD grid-independent?
   Yes for the accepted Medium -> Fine adjacent pair under the requested rule: CD_total changes by `-1.444%` and CD_primary by `-1.443%`. Coarse is not in the same asymptotic drag band because Coarse -> Medium CD_total changes by `-5.492%`.

5. Can `CD≈0.0315` be trusted?
   No. The accepted Medium/Fine family supports Fine `CD_total_physical=0.03326556` and Medium `0.03375281`; `0.0315` is `-5.307%` versus Fine and `-6.674%` versus Medium, so it is too low for this locked setup.

6. Can design power be updated?
   No design power update is made or authorized by this verdict. The CFD drag is now grid-stable on the Medium/Fine pair, but any design-power revision must be a separate same-basis power calculation that does not double-count AVL induced drag or mix this physical-wing CFD coefficient with the old screening CD composition.

Engineering boundary:

- The result is a locked-setup OpenFOAM wing-drag grid-stability verdict, not final aircraft sign-off, RFQ/procurement truth, transition validation, or an AoA/CL sweep.
- yPlus is valid and low on the primary airfoil walls; artificial side/tip closure patches remain diagnostic and are excluded from `total_physical`.
- Use Fine as the best current grid-stable coefficient for this family; do not average in Coarse for drag.
