# WO-006G SU2 CFD V&V Reset and Toolchain Escalation Dossier

Date: 2026-05-13

Allowed verdict: `su2_toolchain_escalation_required_after_exhaustive_failure`

## Scope

This dossier covers the current Baseline A main-wing SU2 recovery campaign. It
does not change Baseline A external geometry, mass authority, span authority, or
the Phase J mainline. AVL, XFOIL, VSPAERO, and proxy results remain sanity checks
only; they are not substitutes for SU2.

Authority basis remains:

- design gross mass: `98.5 kg`
- full span: `34.332286 m`
- half span: `17.166143 m`
- SU2 reference area: `33.420059598 m^2`
- SU2 reference chord: `1.003721543 m`
- cruise speed for the current audit: `6.5 m/s`

At rho = `1.225 kg/m^3`, the required lift coefficient is about `CL = 1.12`.
That makes the current no-BL and broken-BL results easy to reject: `CD ~0.5-0.9`
would imply several kilowatts of drag power and is not human-powered-aircraft
order of magnitude.

## Verdict

No current Baseline A SU2 result is physically credible, and no current result
is even low-confidence ready.

The honest campaign verdict is:

```text
su2_toolchain_escalation_required_after_exhaustive_failure
```

This is not based on one failed mesh or one solver setting. It is based on the
combined result of old high-cell archaeology, WO-006R3/R4/R5/R6 repair attempts,
WO-006F solver attempts, official CFD V&V research, OpenVSP/Gmsh geometry
diagnostics, SU2 wall/transition/convergence requirements, and the local compute
environment.

## External CFD Standard Check

NASA's CFD V&V material frames credibility as uncertainty/error control, not as
solver execution. NASA's spatial convergence guidance recommends three grid
levels to estimate observed order and check asymptotic behavior; two-grid GCI is
allowed but less reliable. NASA DPW experience shows that serious aircraft drag
prediction moved into multi-million to tens-of-millions point grids. A direct
HPA reference, Vanderhoydonck et al. 2016, used a Daedalus half-aircraft
STAR-CCM+ simulation with a 15-layer, 20 mm inflation layer, 5 mm maximum
surface edge size, and 52 million cells. The same paper states that low-Re HPA
drag prediction needs transition modeling.

Relevant source anchors:

- NASA V&V overview: https://www.grc.nasa.gov/WWW/wind/valid/tutorial/overview.html
- NASA spatial convergence and GCI: https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html
- NASA CRM/DPW resolution growth: https://ntrs.nasa.gov/citations/20190027400
- HPA Daedalus CFD mesh and transition discussion: https://www.mdpi.com/2226-4310/3/3/26
- SU2 convergence criteria: https://su2code.github.io/docs_v7/Solver-Setup/
- SU2 wall functions / wall resolution: https://su2code.github.io/docs_v7/Theory/
- SU2 incompressible RANS tutorial mesh expectation: https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/
- SU2 transition model options: https://su2code.github.io/docs_v7/Physical-Definition/
- OpenVSP CompGeom purpose: https://www.nasa.gov/reference/openvsp-comp-geom/

## Existing Evidence Classification

| Evidence | What it proves | Why it is not a result |
| --- | --- | --- |
| WO-006R3 `wing_h=0.12 m` no-BL mesh, `936,017` cells, marker pass, 75 SU2 iterations | Current GO geometry can reach a serious no-BL SU2-readable route | No BL/y+, timeout at 75 iterations, no grid family, not viscous drag evidence |
| Old mesh-native freeze `wing_h=0.20 m`, `1,125,409` cells, `992,352` BL prisms, 10-iteration smoke | A million-cell BL mesh route existed for older mesh-native line | Not current Baseline A final mesh, 10-iteration smoke only, no force stability or grid independence |
| Old BL force-marker audit, `CL=0.450`, `CD=0.723` | Marker force ownership and sign convention were inspectable | Lift too low, drag absurd, not HPA order of magnitude |
| Old no-BL 1000-iter case, `CL=0.260`, `CD=0.153` | Solver can stabilize on a no-BL mesh | No BL/y+, CL far below operating point, CD too high, no grid study |
| WO-006F no-BL RANS attempt 06, `CL=1.289`, `CD=0.556` | Lift sign/magnitude can be forced into the operating band | Drag is physically impossible for HPA and Cauchy did not pass |
| WO-006F Euler attempts | Useful sign and transient diagnostics | Positive drag windows drift to negative drag; not stable force evidence |
| WO-006F attempt 10 multizone | SU2 multizone can launch | Original artifact has no CL/CD output; later force-output probes still produce absurd drag because topology is not valid |
| WO-006R6 core-interface repair | The blocker is narrowed to core quality plus wake/span-cap topology | Final handoff gate is blocked: no merged BL+core SU2, unmatched faces, non-positive core elements |
| Current OpenVSP STEP/STL export | Geometry can be exported | STEP imports as open surfaces/no OCC solid; STL has duplicate, zero-area, and non-manifold defects; Gmsh reports overlapping facets |
| OpenVSP CompGeom diagnostic | VSP3 area bookkeeping is possible | CompGeom warns `1 open meshes merged`; current VSP3 is not a clean watertight CFD solid |

## Why Current Tools Cannot Produce the Required Result

The current local toolchain is:

- OpenVSP Python / vspscript
- Gmsh 4.15.2-git
- local SU2 installation
- macOS workstation with 16 GB RAM and 10 CPUs

The toolchain can produce route/debug evidence. It has not produced the minimum
artifact needed for SU2 aerodynamic evidence: a current Baseline A, wall-owned,
quality-passing, BL-resolved or transition-ready mesh family.

The controlling blockers are:

1. Geometry is not a clean CFD solid. Current OpenVSP CompGeom can compute areas,
   but reports an open merged mesh. Existing STEP imports as loose/open surfaces,
   and existing STL has local degenerate/non-manifold defects. This is upstream
   of SU2.
2. Current Baseline A BL/core topology is not conformal. R6 still has unmatched
   `wake_cut` and `span_cap` faces and a non-watertight full non-wall BL
   boundary. Nonmatching multizone interpolation is not acceptable force truth
   for this case.
3. Current preserved core quality is not solver-grade. R6 reports non-positive
   core volumes/SICN/SIGE and blocks final handoff.
4. Existing coefficient runs are not V&V qualified. They lack wall-resolved BL
   proof, transition-model readiness, force Cauchy/late-window stability, and
   grid independence.
5. The required mesh scale is likely beyond the local workflow. HPA-grade
   reference work uses tens of millions of cells. The current local machine has
   16 GB RAM; even before SU2 runtime, the current geometry/meshing route cannot
   generate one qualified coarse/medium/fine family.

## Minimum Gate for Any Future SU2 Claim

A future result may be promoted only if all gates pass:

1. Data authority gate: `98.5 kg`, `34.332286 m` span, `17.166143 m` half-span,
   and current `Sref/Cref/Bref` are used or explicitly marked as sensitivity.
2. Geometry gate: current Baseline A external geometry is either a watertight CFD
   solid or an explicitly validated thin-wall CFD workflow. Diagnostic geometry
   variants must be labeled non-Baseline.
3. Mesh gate: wall marker ownership passes, no marker orphan faces, no
   non-positive volume elements, no unmatched BL/core interface faces, and
   smooth transition from prism/BL cells to outer volume.
4. Near-wall gate: wall-resolved or wall-function treatment is explicit. For
   wall-resolved RANS, y+ must be demonstrated on the actual run, not estimated
   from a disconnected block.
5. Physics gate: low-Re HPA transition risk is addressed. Fully turbulent RANS
   without transition is not enough for profile-drag truth at this operating
   point unless bounded as a sensitivity.
6. Solver gate: force coefficients are literal SU2 force outputs, positive,
   late-window stable, and pass coefficient Cauchy or documented time-window
   stabilization.
7. Grid-study gate: at least coarse/medium/fine or a justified adjacent-pair
   refinement study exists, with effective refinement ratios and uncertainty
   reported for CL, CD, and moment.
8. Magnitude gate: CL must be near the aircraft operating band and CD must be
   HPA order of magnitude. Negative drag or `CD > 0.09` is rejected unless a
   separately proven physical mechanism explains it.

## Escalation Required

The next credible route is not another small local SU2 probe. It requires one of
these toolchain escalations:

- geometry cleanup / remodeling into a CFD-grade closed wing solid or validated
  thin-wall workflow;
- a mesher capable of producing a consistent BL-resolved coarse/medium/fine
  family for this high-aspect-ratio low-Re wing;
- enough compute memory/cores to run multi-million to tens-of-millions cell SU2
  RANS/transition cases;
- a transition-capable SU2 setup validated first on 2D low-Re airfoil or flat
  plate cases before using Baseline A drag as truth.

Until that escalation exists, current SU2 artifacts must remain route/debug
evidence only. They must not be used for Baseline A aerodynamic calibration,
drag/power reopen, release truth, RFQ/procurement, or final aircraft sign-off.
