# Mesh-Native Main-Wing CFD Line Freeze v1

Date: 2026-05-01

## Status

This line is now **paused**. Do not keep tuning it by small patches until the next owner reads this document and chooses a deliberate next experiment.

Short version:

```text
VSP/ESP -> STEP/BREP repair is retired as the CFD geometry critical path.
Mesh-native VSP-section geometry is the best current direction.
The mesh/SU2 pipeline is connected, but the CFD is not yet physically valid.
The next blocker is local BL topology/quality plus low-Re HPA physics setup, not another tiny code gate.
```

## Where To Start

Future agents should read these files in this order before touching this line:

1. This file:
   `hpa_meshing_package/docs/reports/mesh_native_cfd_line_freeze/mesh_native_cfd_line_freeze.v1.md`
2. Method review:
   `hpa_meshing_package/docs/reports/hpa_main_wing_cfd_method_review/hpa_main_wing_cfd_method_review.v1.md`
3. VSP geometry consistency:
   `hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_geometry_consistency/mesh_native_blackcat_vsp_geometry_consistency.v1.md`
4. 1000-iteration no-BL SU2 run:
   `hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_su2_iter1000/mesh_native_blackcat_vsp_su2_iter1000.v1.md`
5. BL force/marker audit:
   `hpa_meshing_package/docs/reports/mesh_native_blackcat_bl_force_marker_audit/mesh_native_blackcat_bl_force_marker_audit.v1.md`
6. HXT / CPU / SU2 smoke profile:
   `hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md`

## Branch Evidence

Recent commits on `codex/high-fidelity-route-architecture` that matter for this line:

```text
310c7db docs: record HXT thread profile
2bc35e1 fix: use HXT for mesh-native Gmsh routes
7d5f572 fix: use four threads for mesh-native CFD pipeline
cd6f5b9 docs: record mesh-native force marker audit
3cd6c5e feat: add mesh-native BL SU2 stability route
```

Do not infer validation from commit count. The branch contains real progress, but it does not yet contain a credible HPA CFD result.

## Local Source Map

Core mesh-native geometry / meshing code:

- `hpa_meshing_package/src/hpa_meshing/mesh_native/blackcat.py`
  - `load_blackcat_main_wing_spec_from_vsp`
  - `run_blackcat_main_wing_boundary_layer_su2_stability_ladder`
- `hpa_meshing_package/src/hpa_meshing/mesh_native/wing_surface.py`
  - deterministic indexed wing surface builder
  - marker-owned surface generation
- `hpa_meshing_package/src/hpa_meshing/mesh_native/gmsh_polyhedral.py`
  - `write_faceted_volume_mesh_with_boundary_layer`
  - `run_faceted_boundary_layer_su2_smoke`
  - `build_wing_feature_refinement_boxes`
- `hpa_meshing_package/src/hpa_meshing/mesh_native/su2_structured.py`
  - `_smoke_cfg_text`
  - `audit_su2_case_markers`
- `hpa_meshing_package/src/hpa_meshing/mesh_native/mesh_stability.py`
  - `select_cheapest_stable_mesh`

Geometry/reference inputs:

- `data/blackcat_004_origin.vsp3`
- `data/blackcat_004_full.avl`

Important generated evidence under `/tmp`:

- `/tmp/hpa_mdo_vsp_faceted_gmsh_bl_probe_20260501/pps32_span2_wing020_hxt_threads4_profile`
- `/tmp/hpa_mdo_vsp_faceted_gmsh_bl_probe_20260501/pps32_span2_wing015_hxt_threads4_mesh_only`
- `/tmp/hpa_mdo_vsp_faceted_gmsh_bl_probe_20260501/pps32_span2_wing020`

These `/tmp` artifacts are not permanent repo truth. The committed reports listed above are the durable record.

## Route Definition

Current experimental route:

```text
OpenVSP .vsp3
  -> extract main-wing sections directly from VSP
  -> resample embedded airfoils
  -> deterministic full-span indexed wing surface
  -> marker-owned boundary faces: wing_wall / farfield
  -> Gmsh built-in geometry, HXT core tetra meshing
  -> optional Gmsh topological BL extrusion
  -> SU2 mesh export / marker audit
  -> SU2 incompressible smoke or long run
```

This is not the old route:

```text
VSP / ESP -> STEP / BREP -> repair PCurve / station seam -> Gmsh -> SU2
```

The old STEP/BREP repair route is no-go as primary because repeated SameParameter, ShapeFix, projected-PCurve, opcode, and export-format variants did not recover the station-seam metadata gate. See the station-seam report family under:

```text
hpa_meshing_package/docs/reports/main_wing_station_seam_*/
```

## Geometry Findings

The VSP-native mesh-native builder is preferred over the old AVL-driven mesh-native builder.

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_geometry_consistency/mesh_native_blackcat_vsp_geometry_consistency.v1.md
```

What matched:

- `Sref = 35.175 m^2`
- `Bref = 33.0 m`
- chord schedule: `1.30, 1.30, 1.175, 1.04, 0.83, 0.435 m`
- embedded VSP airfoil sections, including the high-lift inboard section and Clark-Y-smoothed tip section
- whole-wing incidence around `3 deg`

What did not match in the older AVL-driven source:

- outboard leading-edge sweep / `x_le` placement
- projected station span under dihedral
- leading-edge `z` placement
- twist axis convention

Engineering read:

```text
Do not call the old AVL-driven mesh-native geometry identical to VSP.
For CFD geometry, use VSP-native section extraction.
Keep AVL as reference / comparison, not as the geometric source of truth.
```

## Mesh Methods Tried

### 1. No-BL tetrahedral mesh

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_high_density_su2_smoke/mesh_native_blackcat_vsp_high_density_su2_smoke.v1.md
hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_su2_iter1000/mesh_native_blackcat_vsp_su2_iter1000.v1.md
```

What worked:

- VSP-native geometry generated million-class no-BL tetra meshes.
- SU2 could read and run them.
- A 1000-iteration viscous no-BL run completed with positive CD.

Representative no-BL long-run result:

```text
volume elements: 717,901
solver: INC_NAVIER_STOKES
wall BC: MARKER_HEATFLUX=(wing_wall,0.0)
final CL: 0.259913
final CD: 0.153472
final CMy: -0.090395
```

Why it is not valid physics:

- no prism boundary layer;
- no wall-normal y+ report;
- drag is dominated by near-wall gradients at this Reynolds number;
- result is far from the VSPAERO panel reference and not grid-independent.

### 2. Wall-resolved BL mesh with Gmsh topological extrusion

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_blackcat_bl_force_marker_audit/mesh_native_blackcat_bl_force_marker_audit.v1.md
hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md
```

Parameters used in the main valid BL mesh:

```text
points_per_side:       32
spanwise_subdivisions: 2
wing_h:                0.20 m
feature_h:             0.32 m
farfield_h:            8.0 m
BL first height:       5.0e-5 m
BL growth ratio:       1.24
BL layers:             24
Gmsh threads:          4
Gmsh Algorithm3D:      10 (HXT)
```

Result:

```text
nodes:                 531,054
volume elements:       1,125,409
BL prisms:             992,352
core tets:             133,057
mesh quality gate:     pass
BL non-positive count: 0
```

This is the best current mesh evidence.

Important caveat:

```text
The mesh is readable and marker-owned, but BL p01 quality is still low.
This is not a final production mesh.
```

### 3. Finer BL mesh attempt

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md
```

`wing_h = 0.15 m` result:

```text
nodes:                         695,550
volume elements:               1,515,251
BL prisms:                     1,281,312
mesh gate:                     fail
BL non-positive minSICN count: 2
BL non-positive minSIGE count: 2
```

Engineering read:

```text
Do not run SU2 on this 0.15 m BL mesh.
The failure is probably local BL extrusion around sharp TE / tip / cap topology.
It is not evidence that the full route is impossible, and it is not solved by simply increasing global tet density.
```

## Gmsh CPU / Parallelism

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md
```

Current code sets:

```text
General.NumThreads      = 4
Mesh.MaxNumThreads1D    = 4
Mesh.MaxNumThreads2D    = 4
Mesh.MaxNumThreads3D    = 4
Mesh.Algorithm3D        = 10
```

CPU profile on the valid 1.125M BL mesh:

```text
max CPU:              358.7 %
average CPU:          119.13 %
samples >= 250 %:     9 / 86
max RSS:              945.8 MB
wall time:            172.03 s
```

Engineering read:

```text
HXT uses multiple cores briefly.
The whole Gmsh BL pipeline is not effectively 4-core end-to-end.
Large parts of geometry construction, surface meshing, and BL extrusion still behave serially.
```

This matters for future 5M-cell ambitions: the RAM budget is probably not the first blocker yet; BL topology and serial meshing phases are.

## SU2 Methods Tried

### Marker and reference audit

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_blackcat_bl_force_marker_audit/mesh_native_blackcat_bl_force_marker_audit.v1.md
```

Confirmed:

```text
REF_AREA   = 35.175
REF_LENGTH = 1.130190
geometry source span/area close to VSP reference
INC_VELOCITY_INIT = (6.5, 0, 0)
AOA = 0 deg
CD == CFx at this setup
CL == CFz at this setup
mesh markers: wing_wall, farfield
force marker: only wing_wall
```

Force breakdown from the 1.137M BL case:

```text
surface: wing_wall only
CL = 0.450181
CD = 0.722552
CMy = -0.442323
CD pressure = 0.607320
CD friction = 0.115232
```

Engineering read:

```text
The current force-marker setup is not obviously counting farfield or extra surfaces.
The huge CD is therefore more likely physics/setup/BL/geometry behavior than a marker bookkeeping bug.
```

### 10-iteration HXT BL smoke

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md
```

Result:

```text
mesh elements:     1,125,409
mesh points:       531,054
markers:           wing_wall, farfield
SU2 command:       OMP_NUM_THREADS=4 SU2_CFD -t 4 su2_runtime.cfg
return code:       0
history rows:      10
final CL:          0.0611974
final CD:          0.2552401
final CMy:        -0.0727683
```

Engineering read:

```text
This only proves SU2 can read and step the HXT BL mesh.
Do not interpret coefficients from 10 iterations.
```

### 1000-iteration no-BL run

Evidence:

```text
hpa_meshing_package/docs/reports/mesh_native_blackcat_vsp_su2_iter1000/mesh_native_blackcat_vsp_su2_iter1000.v1.md
```

Result:

```text
final CL = 0.259913
final CD = 0.153472
final CMy = -0.090395
last-200 coefficient range tiny
```

Engineering read:

```text
CD is not persistently negative after the long viscous run.
Earlier negative CD was probably an Euler/slip-wall or setup-route issue, not a universal SU2 force-sign bug.
But no-BL drag is not credible for this HPA main wing.
```

## Current Physics Concerns

### 1. Low-Re human-powered aircraft regime

The current reference speed is:

```text
V = 6.5 m/s
rho = 1.225 kg/m^3
mu = 1.7894e-5 Pa*s
Cref = 1.13019 m
```

This gives chord Reynolds number around `5.0e5` using `Cref`, with local chord variation across the wing.

Engineering implication:

```text
Laminar / transitional behavior can matter.
Pure fully turbulent RANS is not guaranteed to match VSPAERO or real HPA physics.
But starting with INC_RANS + SA wall-resolved is still a reasonable engineering baseline before adding transition complexity.
```

### 2. Drag credibility

Unreasonable signs seen so far:

- no-BL SU2 long run gave `L/D = 1.69`, far below VSPAERO panel `L/D ~= 28.6`;
- BL force audit gave very large `CD ~= 0.72`;
- pressure drag dominated the BL force breakdown;
- no accepted grid-independence result exists.

Do not use any current CD for aircraft performance.

### 3. Lift mismatch

Reference panel result:

```text
VSPAERO CLtot ~= 1.287645 at V=6.5 m/s, AoA=0 deg
```

Current SU2 evidence is much lower:

```text
no-BL 1000-iter CL ~= 0.260
BL force-audit CL ~= 0.450
```

Possible causes that remain open:

- geometry incidence / airfoil / camber extraction mismatch;
- finite-wing tip / farfield / domain effects;
- no transition modeling;
- wall-resolved BL extrusion local defects;
- SU2 setup not comparable to VSPAERO panel assumptions;
- reference convention mismatch still possible beyond Sref/Cref/Bref.

Do not conclude "geometry is wrong" from CL alone yet.

### 4. Boundary layer topology

The route currently uses Gmsh topological BL extrusion from faceted wing surfaces. This is practical, but it is not a fully owned near-wall topology.

The failed `wing_h = 0.15 m` BL mesh is the warning sign:

```text
two BL prism quality failures appeared when pushing denser.
```

This points to local TE/tip/cap topology, not global mesh count.

### 5. Half-wing symmetry not implemented in this route

Half-wing symmetry is still a good idea for RAM and cell budget, but it should not be bolted on casually.

Need to define:

- root-plane `symmetry` marker;
- half-domain farfield;
- whether SU2 uses half `REF_AREA` or post-process doubles forces;
- root cap vs symmetry surface ownership;
- comparison case proving full-wing / half-wing coefficient normalization agrees.

## External Method Notes

Official references checked for this line:

- Gmsh documents `Mesh.Algorithm3D = 10` / HXT as a parallel Delaunay-style 3D algorithm and documents size fields / BL extrusion behavior:
  https://gmsh.info/doc/texinfo/
- SU2 marker documentation defines marker-owned boundary conditions including `MARKER_EULER`, `MARKER_HEATFLUX`, `MARKER_FAR`, and `MARKER_SYM`:
  https://su2code.github.io/docs_v7/Markers-and-BC/
- SU2 theory docs note SA/SST support for `RANS` / `INC_RANS` and wall-resolved requirements when wall models are not active:
  https://su2code.github.io/docs_v7/Theory/
- SU2's incompressible turbulent NACA0012 tutorial is a useful baseline pattern for `INC_RANS + SA + no-slip + farfield` setup:
  https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/
- NASA Turbulence Modeling Resource NACA0012 grids are useful as a scale reference for wall-normal resolution and grid-convergence intent, not as a direct 3D HPA wing mesh recipe:
  https://turbmodels.larc.nasa.gov/naca0012numerics_grids.html

## Why This Line Is Paused

Pause reasons:

1. The pipeline is connected, but not validated.
2. The best BL mesh is only 1.125M cells and has low near-wall quality warnings.
3. The next denser BL mesh failed local prism quality.
4. SU2 short smoke works, but 10 iterations are not physics.
5. The long no-BL run is numerically flat but physically not credible for drag.
6. Current CL/CD are not close enough to VSPAERO to claim a useful HPA CFD setup.
7. Continuing with small global mesh-size changes is likely wasted until the local BL defect is understood.

## Next Things To Try

Recommended next experiments, in order:

### A. Localize the `wing_h = 0.15 m` BL failure

Goal:

```text
Find the exact station / chord / marker / face family responsible for the 2 bad BL prisms.
```

Try:

- write worst-BL-cell coordinates and source surface ids to report;
- correlate with TE, tip cap, root cap, and feature-refinement boxes;
- export a small VTK/CSV subset for inspection;
- test local TE/tip cap smoothing or BL truncation only after localization.

Do not:

```text
Blindly lower global h again.
```

### B. Build a half-wing symmetry route

Goal:

```text
Reduce cell count and RAM while preserving coefficient normalization.
```

Required evidence:

- root `symmetry` marker in mesh;
- `MARKER_SYM` in SU2 config;
- half/full reference convention documented;
- half/full smoke comparison at a coarse level;
- no overlapping root wall and symmetry surface.

### C. RANS wall-resolved baseline

Goal:

```text
Create a first physically reasonable viscous baseline before transition modeling.
```

Suggested first setup:

```text
solver: INC_RANS
turbulence model: SA
wall: no-slip adiabatic
y+ target: around 1
first layer: around 5e-5 m as first estimate
iterations: up to 2000
```

Acceptance should be engineering-based:

- residuals and coefficients stable;
- CL/CD/CMy not drifting over last window;
- no negative or absurd drag;
- compare to VSPAERO only after convergence and reference convention checks.

### D. Mesh independence ladder

Only after A/B/C:

```text
coarse / medium / fine half-wing BL meshes
target cell counts roughly around 1M / 2M / 3M first, then revisit 5M+
RAM cap: about 12 GB
```

Selection rule:

```text
Pick the cheapest adjacent pair with stable CL/CD/CMy changes.
Do not promote a mesh just because it is large.
```

### E. Transition / low-Re physics

After wall-resolved RANS baseline is stable:

- investigate transition modeling or laminar/turbulent assumptions;
- compare section behavior to XFOIL / airfoil polar evidence where available;
- do not start with transition as the default route unless the baseline RANS route is numerically healthy.

## Explicit No-Go Items

Do not:

- revive VSP/ESP STEP/BREP repair as the CFD primary path;
- use `wing_h = 0.15 m` BL mesh for SU2 before fixing the bad prisms;
- claim physical validation from 10/60/100-iteration smoke runs;
- trust no-BL tetra CD for HPA performance;
- push to 5M cells before fixing local BL quality;
- treat VSPAERO exact match as a gate before SU2 convergence and setup sanity;
- treat the current mesh gates as absolute physics truth. They are diagnostics.

## Current Bottom Line

This line is worth keeping, but not worth blindly continuing today.

The useful result is:

```text
Mesh-native VSP geometry -> Gmsh HXT BL mesh -> SU2 marker-owned smoke is real.
```

The unresolved engineering problem is:

```text
Make the near-wall BL topology and low-Re CFD setup physically credible before spending 5M-cell compute.
```
