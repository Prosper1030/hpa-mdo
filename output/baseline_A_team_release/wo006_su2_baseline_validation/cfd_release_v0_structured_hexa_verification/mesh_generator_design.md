# Mesh Generator Design

The generator creates a closed quadrilateral body surface for the full Baseline A
wing, including split upper/lower wall patches, TE/closure strips, and structured
quad tip disks. It then computes smoothed outward vertex normals and inflates the
closed surface to a body-like farfield with the same topology. Radial layers are
connected face-by-face, so every volume cell is a hexahedron.

No automatic layer insertion, unstructured core fill, snappyHexMesh, cfMesh,
Gmsh, TetGen, meshpy, receiver caps, or cycle caps are used. OpenFOAM polyMesh is
written directly as points, faces, owner, neighbour, and boundary files.

The first cell height is explicit in the radial distribution. The default
Baseline debug route uses n_span=32, n_perimeter=96, radial_layers=40. The
verification route uses n_span=64, n_perimeter=160, radial_layers=80.
