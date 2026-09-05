# References

External literature and tool documentation this project relies on.

These are **not redistributed here**. Obtain each from its publisher or the tool's own
distribution.

## Literature

**Drela, M. (2012).** *Low Reynolds Number Airfoil Design for the M.I.T. Daedalus Prototype:
A Case Study.* AIAA Journal of Aircraft.
→ Airfoil design rationale at HPA Reynolds numbers. Available via AIAA ARC.

**Bussolari, S. R., & Nadel, E. R.** *Flight Test Results for the Daedalus and Light Eagle
Human Powered Aircraft.*
→ The primary flight-test dataset used as a reference benchmark in this project. See
`data/reference_aircraft/hpa_benchmarks.yaml` for the values actually used.

**MIT Daedalus structural design literature.**
→ CFRP spar and composite structure rationale. Summarized in
`docs/research/MIT_Daedalus_Composite_Structure_Rationale.md`.

> Reference data extracted from these sources is used for benchmark comparison only. This
> project has **no flight-test correlation of its own** — the Daedalus data is a sanity check
> against a *different* aircraft, not validation of this one.

## Tool documentation

| Tool | Use here | Documentation |
|---|---|---|
| **AVL** (Drela / MIT) | Vortex-lattice aerodynamics, in-loop | https://web.mit.edu/drela/Public/web/avl/ |
| **ASWING** (Drela / MIT) | Nonlinear aeroelastic analysis (planned, not yet integrated) | https://web.mit.edu/drela/Public/web/aswing/ |
| **CalculiX** | Independent FE cross-check | https://www.calculix.de/ |
| **OpenVSP** (NASA) | Parametric geometry, VSPAERO panel method | https://openvsp.org/ |
| **SU2** | RANS CFD | https://su2code.github.io/ |
| **OpenFOAM** | RANS CFD — the WO-006 grid-convergence campaign | https://www.openfoam.com/ |
| **gmsh** | Mesh generation | https://gmsh.info/ |
| **OpenMDAO** (NASA) | MDO framework | https://openmdao.org/ |
| **QPROP** (Drela / MIT) | Propeller analysis | https://web.mit.edu/drela/Public/web/qprop/ |

## Note on removed files

`docs/Paper/` and `docs/Manual/` previously contained PDF copies of several of the above. They
were removed in 2026-09 because redistributing publisher-copyrighted papers and licensed tool
manuals is not permitted. The citations above replace them.

Those files remain reachable in this repository's git history; they were **not** purged by a
history rewrite, since rewriting 1,300+ commits carries more risk than the exposure warrants.
If a rights-holder objects, history removal can be done deliberately at that point.

One file, `docs/Paper/hpa_structure.pdf`, carries no identifying metadata and its provenance
could not be established. It was removed for the same reason: unknown provenance is not a basis
for redistribution.
