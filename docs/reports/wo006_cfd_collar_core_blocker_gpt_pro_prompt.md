# WO-006 CFD Collar/Core Blocker Prompt

Date: 2026-05-15

Use this packet when asking GPT Pro or a meshing specialist for the next
topology decision.  The goal is not another solver-numerics suggestion; the
answer should be a concrete hybrid-mesh topology recipe for the current
collar/core dual-volume blocker.

## Current Route State

- Active CFD route: `canonical_hybrid_halfwing_v0`.
- Retired forensic routes: R25/R26/R27/R28/R29/R30 and the old custom all-tet /
  global-star / owner-pyramid / closure-repair handoff.
- Passed manifest gates: `TOOLCHAIN_PASS`, `PRESSURE_SANITY_PASS`.
- Pending manifest gate: `ROUTE_SMOKE_PASS`.
- Phase 1 evidence: 2D wall-resolved `INC_RANS/SA` sanity passes with CD about
  `0.020-0.021`.
- Phase 2 evidence: 3D half-wing pressure-only sanity passes with
  `CD=0.01778726857` and SU2 max CV sub-volume ratio `186725`.

## What Has Already Been Tried

- Minimal artificial `prism -> pyramid -> tet` topology unit passes:
  `tet_to_prism_quad_contact=0`, positive prism/pyramid/tet volumes, and SU2
  marker ownership pass.
- Real-wing partial-BL transition collar at pps42/l24 converts prism rim quads
  to internal pyramid bases:
  `124,416` prisms, `3,480` pyramids, `13,920` collar-interface triangles,
  `force_wall_rim_marker_leak_count=0`, positive pyramid volumes.
- Small collar+cap core probe at pps12/l4 tetra-fills.
- Thin-collar pps42 core scale probes tetra-fill at l4/l8/l16, but runtime grows
  quickly.
- Merged pps12/l4 hybrid SU2 writer passes marker ownership and removes internal
  `bl_outer_interface` / `transition_collar_interface` markers.
- Merged pps12/l4 pressure-only SU2 reads the mesh but fails at iteration `2`:
  min orthogonality `0.0105006 deg`, max CV face-area aspect `7.58862e9`,
  max CV sub-volume ratio `4.37135e11`.
- GPT Pro suggested Build 1 pps42/layers=3 was also run:
  `15,552` prisms + `435` pyramids + `15,705` tetra, root sidewall aspect about
  `966`, direct prism quality gate pass, but mixed dual proxy still fails with
  max CV sub-volume ratio about `3.3939807886633167e11`.
- Whole-interface non-wall transition buffer produced `15,980` buffer prisms and
  passed prism signed-volume checks, but Gmsh core fill blocked with
  `Invalid boundary mesh (overlapping facets)`.
- A naive Gmsh Distance/Threshold background size field near the whole inner
  boundary was attempted as an uncommitted experiment and became non-Mac-safe on
  pps12/l4; do not suggest "just refine near interface" unless the recipe is
  bounded/local enough for a 16 GB Mac route-smoke probe.

## Latest Hotspot Geometry Evidence

For pps42/layers=3, the worst dual-proxy point is:

```text
x = 0.8718563237833309
y = 11.630095010662876
z = 1.0602261260094792
source_pair = tetra_core|tetra_core
incident_element_source_counts = {"tetra_core": 16, "transition_collar_pyramid": 1}
```

Incident geometry at that point:

```text
tetra_core:
  count = 16
  min_abs_volume_m3 = 6.69299205751043e-13
  max_abs_volume_m3 = 0.22715885405372496
  min_edge_length_m = 5.9999999999848376e-05
  max_edge_length_m = 1.6789889759830705
  max_edge_length_ratio = 13672.367448040834

transition_collar_pyramid:
  count = 1
  abs_volume_m3 = 1.8833379397242847e-09
  min_edge_length_m = 7.199999999985765e-05
  max_edge_length_m = 0.7855249804387457
  max_edge_length_ratio = 10910.069172781929
```

Engineering read: the current collar/core topology makes a single vertex see
BL/collar-scale edges around `6e-5 m` and meter-scale core edges.  That scale
jump reproduces the SU2 vertex-dual control-volume pathology even when marker
ownership and primal signed volumes pass.  The pre-solver proxy now gates this
directly with `max_hotspot_incident_edge_length_ratio=1000`; the pps42/layers=3
report-level maximum is `39059.367143113835`, so it is blocked before any
pressure or RANS run.

Update after the latest probe: an artificial segmented-collar scale-transition
unit now passes the pre-solver gates.  It splits the long prism rim into `16`
short segments before pyramid collar handoff, writes `32` prisms + `16`
pyramids + `96` tetra, keeps rim quad max edge ratio about `500`, has
`tet_to_prism_quad_contact=0`, and passes the dual proxy.  The open question is
how to apply this segmentation/ramp rule to the real-wing TE/tip/closure rim
without changing force-wall markers or creating cap self-intersections.  For the
current pps42/l24 real-wing handoff, the single-pyramid rim quads have max base
edge ratio about `1.64e4`; the current estimate to keep every segmented base
below `1000` is `6,928` rim pieces total (`te_wall=4,376`, `tip_wall=1,944`,
`closure_wall=608`).  The report now contains a per-quad
`split_longest_prism_rim_edge_pair` plan; the predicted maximum post-split base
edge ratio is about `997.8`.  Collapsing the layer-expanded plan back to the
source mesh gives `145` source rim edges and about `809` required source-edge
segments (`te_wall=640`, `tip_wall=81`, `closure_wall=88`).

## Question To Answer

Please propose the next concrete topology recipe, not solver numerics.

Which route should we implement next, and what are the exact construction rules?

Candidates:

1. Local termination ramp / smoothed BL outer surface only around TE/tip/closure
   stageback zones.
2. Structured transition patch around the collar rim that grows from
   `O(1e-4 m)` BL/collar edges to `O(0.05-0.2 m)` core edges before Gmsh sees the
   tetra core.
3. Replace the single-apex pyramid collar with a segmented or multi-row
   prism/pyramid/tet transition collar with controlled edge growth.
4. Abandon partial-BL collar for now and return to closed-wall wrapper with TE
   stageback smoothing.
5. Use cfMesh/snappyHexMesh/OpenFOAM selective layer generation as a topology
   cross-check, then convert only if the force/pressure sanity is credible.

The answer should specify:

- Which geometry entities are physical wall markers vs internal interfaces.
- How the BL termination/collar region avoids exposed prism rim quads.
- How local edge growth is controlled so no core tet incident to the collar has
  `max_edge/min_edge` in the `1e4` range.
- A minimal Mac-safe topology unit test before full wing.
- A pps42/layers 3 -> 8 -> 16 -> 24 build-up rule.
- Pre-solver gates for signed volumes, exposed internal faces, marker ownership,
  and SU2-style dual proxy.
