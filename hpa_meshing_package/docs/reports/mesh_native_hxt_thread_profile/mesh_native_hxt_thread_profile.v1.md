# Mesh-Native HXT Thread Profile V1

Date: 2026-05-01

## Question

Confirm whether the mesh-native Blackcat main-wing Gmsh/SU2 pipeline is actually using the 4-core CPU budget, and check the current SU2 pipeline status after switching the production mesh-native route to Gmsh HXT (`Mesh.Algorithm3D = 10`).

## Code status

Committed pipeline change:

```text
2bc35e1 fix: use HXT for mesh-native Gmsh routes
```

The mesh-native Gmsh route now reports both:

```text
gmsh_threads = 4
mesh_algorithm3d = 10
```

The route still leaves the preserved-quad BL-block core helper on `Mesh.Algorithm3D = 1`, because HXT rejects preserved non-triangular discrete boundary surfaces.

## CPU profile result

Profiled case:

```text
/tmp/hpa_mdo_vsp_faceted_gmsh_bl_probe_20260501/pps32_span2_wing020_hxt_threads4_profile
```

Geometry:

```text
source geometry: data/blackcat_004_origin.vsp3
reference:       data/blackcat_004_full.avl
points_per_side: 32
spanwise_subdivisions: 2
wing_h:          0.20 m
feature_h:       0.32 m
farfield_h:      8.0 m
BL first height: 5.0e-5 m
BL growth ratio: 1.24
BL layers:       24
```

Observed CPU profile:

```text
samples:                 86
max CPU:                 358.7 %
average CPU:             119.13 %
samples >= 150 % CPU:    9
samples >= 250 % CPU:    9
max RSS:                 945.8 MB
mesh wall time:          172.03 s
```

Engineering interpretation:

```text
The HXT 3D phase does use multiple cores briefly.
The whole pipeline is not effectively 4-core end-to-end.
Large portions of built-in geometry construction, surface meshing, and BL extrusion still behave serially.
```

So the correct answer is not "single-core only" and not "fully 4-core". It is:

```text
Gmsh is configured for 4 threads and HXT does spike to about 3.6 cores, but average CPU is only about 1.2 cores over the full mesh build.
```

## Mesh quality result

The `wing_h = 0.20 m` HXT BL mesh passed the current quality gate:

```text
nodes:          531,054
volume elems:   1,125,409
volume types:   tets + prisms
mesh gate:      pass
BL prisms:      992,352
core tets:      133,057
```

Boundary-layer quality:

```text
BL non-positive minSICN count: 0
BL non-positive minSIGE count: 0
BL non-positive volume count:  0
BL minSICN:                   7.605e-6
BL minSIGE:                   3.857e-3
BL p01 minSICN:               6.784e-4
```

Engineering interpretation:

```text
This is a readable 1.1M-cell wall-resolved BL mesh.
It is still not a high-quality final CFD mesh: near-wall p01 quality is low and the BL has very small cells near sharp geometry.
```

The more aggressive `wing_h = 0.15 m` HXT mesh reached 1.52M cells but failed the BL quality gate:

```text
nodes:                         695,550
volume elems:                  1,515,251
BL prisms:                     1,281,312
core tets:                     233,939
BL non-positive minSICN count: 2
BL non-positive minSIGE count: 2
mesh gate:                     fail
```

Engineering interpretation:

```text
Do not run SU2 on the 0.15 m case yet.
This is likely a local BL extrusion problem near sharp TE/tip/cap topology, not a global volume tet density problem.
```

## SU2 pipeline check

The `wing_h = 0.20 m` HXT mesh was converted to SU2 and passed marker audit:

```text
mesh:       mesh.su2
NDIME:      3
NELEM:      1,125,409
NPOIN:      531,054
NMARK:      2
markers:    wing_wall, farfield
wing_wall:  41,348 boundary elements
farfield:   4,076 boundary elements
```

SU2 command:

```text
OMP_NUM_THREADS=4 SU2_CFD -t 4 su2_runtime.cfg
```

SU2 10-iteration smoke result:

```text
return code:      0
history rows:     10
final iteration:  9
final CL:         0.0611974
final CD:         0.2552401
final CMy:       -0.0727683
```

Engineering interpretation:

```text
The HXT mesh is SU2-readable.
The markers are owned correctly.
SU2 runs with the 4-thread command.
The 10-iteration coefficients are not physical evidence; this only confirms the mesh and solver pipeline still connect.
```

## Current pipeline verdict

```text
Gmsh thread setting:       fixed and observable
Actual Gmsh parallelism:   partial, not end-to-end
1.1M BL mesh:              generated, marker-owned, SU2-readable
1.5M BL mesh:              generated but rejected due local BL quality failure
SU2 smoke on HXT mesh:     pass
Long converged SU2 run:    not rerun on the new HXT mesh yet
```

Next engineering move:

```text
Keep wing_h = 0.20 as the current valid high-density BL mesh.
Fix the local BL extrusion quality before pushing below wing_h = 0.20.
Do not spend time increasing global tet density until the 0.15 m BL defect is localized.
```
