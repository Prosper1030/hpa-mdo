# Phase 3 Verification-Grade Verdict

## Short Verdict

No verification-grade 3D CFD case was produced. The bounded mature open-source route sequence was exhausted on this Mac without producing an accepted wall-function or wall-resolved Baseline A main-wing CD validation case. The exact blocker is near-wall mesh generation and yPlus control, not solver startup and not tip/TE/closure force contamination.

## Required Questions

1. Was a verification-grade 3D CFD case produced?

   No.

2. Which mature mesh route succeeded?

   None. cfMesh/cartesianMesh/pMesh, pyHyp/body-fitted, Gmsh CAD-first/surface-based, and strict snappy absolute-layer fallback were all bounded-attempted. Strict snappy produced finite high-yPlus sanity cases only.

3. What are CD_primary, CL_primary, CD_total?

   No accepted verification-grade values exist. The closest rejected high-yPlus case is `wall_resolved_target`: `CD_primary=0.07326929`, `CL_primary=0.9215704`, `CD_total=0.07332259`.

4. Are pressure/viscous contributions available, and what are they?

   No. Current OpenFOAM `forceCoeffs` outputs do not provide a pressure/viscous split. `Cd(f)` and `Cd(r)` are front/rear axle coefficients in OpenFOAM `forceCoeffs.H`, not pressure and viscous drag.

5. What are yPlus mean/p95/max on wing_upper and wing_lower?

   For the closest rejected `wall_resolved_target`: `wing_upper=192.62012089 / 703.5011 / 1611.03`, `wing_lower=128.13073409 / 411.7137 / 1175.49`.

6. Is the result wall-function verification, wall-resolved verification, or still high-yPlus sanity only?

   Still high-yPlus sanity only.

7. Does the CFD support or contradict the existing XFOIL/spanwise-integrated CD estimate?

   Inconclusive. The rejected high-yPlus CFD CD is much higher than the existing screening `CD_total≈0.02602003`, but the mesh fails the near-wall acceptance gate, so that difference cannot be used to accept or reject the XFOIL-derived estimate.

8. Is the result good enough to hand to the engineering team as CFD verification?

   No. It is good enough to hand over as bounded tool evidence and as a meshing procurement/escalation basis, not as aerodynamic CD validation.

9. If not, what exact blocker remains?

   Mesh generation/yPlus/layer coverage. Solver stability is secondary; tip/TE/closure contamination is not the main issue; transition model uncertainty remains but should not be attacked before the mesh gate is solved.

10. If the open-source route fails, what external mesher/tool is most likely required and why?

   A mature body-fitted or industrial prismatic boundary-layer mesher that can preserve split wall markers while generating controlled near-wall spacing around a thin, high-aspect-ratio wing: for example Pointwise, Fidelity/HEXPRESS, ANSYS ICEM/Fluent Meshing, or an equivalent commercial/industrial meshing route. The reason is not convenience; the evidence here shows open-source cartesian layer addition, CAD-first Gmsh, and local pyHyp installation did not produce a verification-grade near-wall mesh on this machine.

## Engineering Trust Boundary

This result should not be marketed as a CFD drag number. It should be documented as: open-source CFD solver path is runnable, but open-source verification-grade near-wall meshing for this Baseline A geometry remains blocked on this Mac. The next engineering action is not another one-parameter snappy tweak; it is either a mature external BL mesher route or a deeper, planned body-fitted meshing environment build outside this repo checkout.
