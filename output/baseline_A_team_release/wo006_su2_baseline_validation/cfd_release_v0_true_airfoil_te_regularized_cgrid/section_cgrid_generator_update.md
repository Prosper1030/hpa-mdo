# Section C-Grid Generator Update

The generator now consumes `open_te_cgrid` airfoil authority with a selectable
`target_zero_te_gap_over_chord`. That makes the TE-gap matrix deterministic
instead of baking a single DAE31 collar gap into the route.

The OpenFOAM runner writes every section/variant case, runs primary
`checkMesh -meshQuality`, then runs
`checkMesh -allTopology -allGeometry -meshQuality` even when the primary command
fails. This preserves exact failure evidence for bounded hard-blocker reports.
