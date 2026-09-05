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

`docs/Paper/` and `docs/Manual/` previously contained copies of several of the documents above.
All were removed in 2026-09. The citations here replace them; each is obtainable from its
publisher or from the tool's own distribution.

| Removed | Reason |
|---|---|
| Drela (2012), AIAA J. Aircraft | Publisher-copyrighted. Redistribution not permitted. |
| Daedalus / Light Eagle flight-test paper | Publisher-copyrighted. |
| `hpa_structure.pdf` | No identifying metadata; provenance could not be established. Unknown provenance is not a basis for redistribution. |
| ASWING Extended User Manual | Distributed with licensed ASWING. Redistribution not permitted. |
| `avl_doc.txt` (AVL 3.40 User Primer) | Ships with AVL. No redistribution grant found. |
| `ccx_2.22.pdf` (CalculiX 2.22 manual) | **Redistribution status could not be verified.** The manual contains exactly one licence reference in 630 pages — *"the present software is protected by the GNU General Public License"* — which covers the **software**, not the document. The manual itself carries no licence statement, no copyright notice and no redistribution grant. Removed rather than assumed permissible. |

The CalculiX entry corrects an earlier assessment in this project's own audit, which had recorded
the manual as GPL-licensed. Reading the document showed that the GPL statement refers to the
solver source, not to the documentation.

Those files remain reachable in this repository's git history; they were **not** purged by a
history rewrite, since rewriting 1,300+ commits carries more risk than the exposure warrants.
If a rights-holder objects, history removal can be done deliberately at that point.

One file, `docs/Paper/hpa_structure.pdf`, carries no identifying metadata and its provenance
could not be established. It was removed for the same reason: unknown provenance is not a basis
for redistribution.
