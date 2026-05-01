# shell_v4 half-wing BL current probe

## Bottom line

The current route is **not ready** for a real Black Cat main-wing 2000-iteration grid-independence CFD run yet.

The important distinction:

- `surrogate_naca0012` half-wing BL mesh: **success**, about 1.18M cells, 24 prism layers, estimated y+ about 0.49-1.04, RAM estimate 9.9 GB.
- real VSP main wing (`esp_rebuilt_main_wing` from `data/blackcat_004_origin.vsp3`): **failed before volume mesh**, with Gmsh PLC segment/facet intersection and 0 achieved BL layers.

So the half-wing BL machinery works on a clean surrogate, but the real high-lift main-wing outboard/tip topology is not valid enough for the physical mesh yet.

## Airfoil check

The real main-wing route is **not using NACA0012**.

The VSP provenance report shows the main wing uses:

- `FX 76-MP-140`
- `CLARK-Y 11.7% smoothed`

with cambered embedded airfoil coordinates. The recorded maximum camber is about `0.0712 c`, and maximum thickness is about `0.141 c`. The NACA result in this probe is only a pipeline/mechanics check for symmetry + prism BL + million-cell memory scale.

## Evidence

## External CFD references

The wider CFD references point in the same direction as the local failures:

- SU2 supports the right low-speed family: `INC_NAVIER_STOKES` / `INC_RANS`, dimensional incompressible setup, no-slip heatflux walls, farfield, symmetry, SA/SST RANS, and LM transition.
- SU2's transition tutorial explicitly frames fully turbulent flow as a simplification that misses transition and separation-bubble behavior. For this HPA Reynolds-number range, `INC_RANS + SA` is a robust first baseline, not the final drag truth.
- NASA/TMR airfoil validation grids use nested C-grid families, very fine wall spacing, and carefully controlled trailing-edge spacing. That is a strong hint that our route should own near-wall topology and TE/wake spacing directly.
- Gmsh's own documentation says topological boundary layers are simple extrusions with no special fan or re-entrant corner treatment. That matches the current real-wing tip/outer-panel failure.

### Surrogate half-wing BL mesh

- case: `/tmp/hpa_mdo_shell_v4_surrogate_bl_mesh_macsafe_current`
- geometry: `surrogate_naca0012`
- status: `success`
- cells: `1,179,420`
- nodes: `484,481`
- BL layers: `24 / 24`
- BL cells: `829,296`
- BL collapse rate: `0.0`
- estimated first-cell y+: `0.49` to `1.04`
- estimated RAM: `9.89 GB`
- gamma p05: `0.101`

Engineering read: this proves the half-wing BL route can hit the rough million-cell class under the 12 GB RAM target, but it does not certify the real VSP wing.

### Real VSP main wing BL prelaunch

- case: `/tmp/hpa_mdo_shell_v4_real_main_wing_bl_prelaunch_current`
- geometry: `esp_rebuilt_main_wing`
- source: `/Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_origin.vsp3`
- status: `failed`
- error: `PLC Error: A segment and a facet intersect at point`
- requested BL layers: `8`
- achieved BL layers: `0`
- failure region: about `y = 14.9 m` outward, near the outboard/tip transition

The automatic protection logic already tried tip truncation and local thickness scaling. The route still fails before a usable volume mesh exists.

### Stage-guard experiment

- case: `/tmp/hpa_mdo_shell_v4_real_main_wing_bl_stage_guard_current`
- candidate: `stage_with_termination_guard_8_to_7_focused`
- status: `failed`
- result: same failure family, still 0 achieved BL layers

Engineering read: this is no longer a good place to keep tuning one small parameter. The problem is the outboard/tip topology family, not simply mesh density or one BL layer count.

### Thin y+ near-wall experiment

- case: `/tmp/hpa_mdo_shell_v4_real_main_wing_thin_yplus_bl_current`
- geometry: `esp_rebuilt_main_wing`
- source: `/Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_origin.vsp3`
- first layer: `5e-5 m`
- layers: `12`
- growth: `1.25`
- total BL thickness: `0.00271 m`
- estimated first-cell y+: `0.49` to `1.04`
- status: `failed`
- error: `PLC Error: A segment and a facet intersect at point`

This was a useful engineering test: it removed the large BL-thickness pressure and avoided the automatic tip-truncation path, but Gmsh still failed in the same PLC/boundary-recovery family. So the next move should not be another tiny thickness tweak. The real blocker is the OCC/Gmsh topology path for this VSP wing.

### Current no-BL SU2 context

The VSP-native no-BL tetra route did run 1000 iterations:

- mesh: `717,901` tetra, `258,378` nodes
- solver: `INC_NAVIER_STOKES`
- final `CL = 0.2599`
- final `CD = 0.1535`
- final `L/D = 1.69`
- last-200 coefficient variation was tiny
- `CD` is positive after the long run

But this is **not** a drag-quality physical CFD result for the low-Re main wing because it has no wall-resolved prism boundary layer.

## Engineering decision

Do **not** launch the requested 2000-iteration real-wing grid-independence run yet. It would either fail at mesh generation, or if we fall back to the no-BL route, it would measure solver stability instead of physical mesh independence.

The next useful engineering task is not global mesh refinement. It is to stop relying on late OCC/Gmsh BL repair for the real main wing:

1. Keep VSP embedded `FX 76-MP-140` / `CLARK-Y` airfoils.
2. Build mesh-native C-grid/O-grid-like near-wall topology from indexed VSP sections.
3. Own chord/span/radial indexing, TE/wake spacing, root symmetry, and tip closure directly.
4. Write SU2 prism/hexa connectivity directly where possible, or only hand the outer block to Gmsh after the near-wall mesh is already valid.
5. After that, run half-wing `INC_RANS + SA` with wall-resolved y+ near 1.
6. Then run coarse/medium/fine around roughly `0.9M / 1.8M / 3.0M` half-wing cells under the 12 GB RAM cap.

Only after that should `CL`, `CD`, and `L/D` be compared against VSPAERO as an aerodynamic sanity check.
