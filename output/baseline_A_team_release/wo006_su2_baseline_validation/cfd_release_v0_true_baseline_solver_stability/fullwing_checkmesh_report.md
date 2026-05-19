# Full-Wing checkMesh Report

- returncode: `0`
- metrics: `{'status': 'completed_with_inherited_quality_flags', 'cells': 1996800, 'maxNonOrtho': 89.193, 'maxSkew': 3.45663, 'negativeVolumeCells': None, 'openCells': None, 'failedChecks': 2, 'error_lines': ['pyramids:      0', 'Face pyramids OK.', 'Failed 2 mesh checks.']}`
- solver-smoke acceptance: `{'command_returncode_zero': True, 'strict_checkMesh_clean': False, 'accepted_for_solver_smoke': True, 'failedChecks': 2, 'metrics': {'status': 'completed_with_inherited_quality_flags', 'cells': 1996800, 'maxNonOrtho': 89.193, 'maxSkew': 3.45663, 'negativeVolumeCells': None, 'openCells': None, 'failedChecks': 2, 'error_lines': ['pyramids:      0', 'Face pyramids OK.', 'Failed 2 mesh checks.']}, 'note': 'strict meshQuality flags are inherited from the accepted half-wing mesh and are not negative-volume/open-cell/oriented-pyramid blockers'}`

        polyhedra:     0

    Checking topology...
        Boundary definition OK.
        Cell to face addressing OK.
        Point usage OK.
        Upper triangular ordering OK.
        Face vertices OK.
        Number of regions: 1 (OK).

    Checking patch topology for multiply connected surfaces...
        Patch               Faces    Points     Surface topology
        airfoil_upper       14976    15229    ok (non-closed singly connected)
        airfoil_lower       14976    15229    ok (non-closed singly connected)
        te_wall             1248     1413     ok (non-closed singly connected)
        outlet              1248     1413     ok (non-closed singly connected)
        farfield            29952    30301    ok (non-closed singly connected)
        physical_tip_right  12800    13000    ok (non-closed singly connected)
        physical_tip_left   12800    13000    ok (non-closed singly connected)
        ".*"                88000    88000    ok (closed singly connected)


    Checking faceZone topology for multiply connected surfaces...
        No faceZones found.

    Checking basic cellZone addressing...
        No cellZones found.

    Checking basic pointZone addressing...
        No pointZones found.

    Checking geometry...
        Overall domain bounding box (-12.5353 -17.1661 -13.617) (12.5275 17.1661 11.6208)
        Mesh has 3 geometric (non-empty/wedge) directions (1 1 1)
        Mesh has 3 solution (non-empty) directions (1 1 1)
        Boundary openness (3.4998e-16 -7.80138e-17 -1.23312e-16) OK.
     ***High aspect ratio cells found, Max aspect ratio: 1431.97, number of cells 68
      <<Writing 68 cells with high aspect ratio to set highAspectRatioCells
        Minimum face area = 8.25668e-10. Maximum face area = 5.80578.  Face area magnitudes OK.
        Min volume = 1.77218e-10. Max volume = 1.61593.  Total volume = 10008.5.  Cell volumes OK.
        Mesh non-orthogonality Max: 89.193 average: 26.4879
       *Number of severely non-orthogonal (> 70 degrees) faces: 83978.
        Non-orthogonality check OK.
      <<Writing 83978 non-orthogonal faces to set nonOrthoFaces
        Face pyramids OK.
        Max skewness = 3.45663 OK.
        Coupled point location match (average 0) OK.
    Checking faces in error :
        non-orthogonality > 90  degrees                        : 0
        faces with face pyramid volume < 1e-18                 : 0
        faces with concavity > 80  degrees                     : 0
        faces with skewness > 4   (internal) or 20  (boundary) : 0
        faces with interpolation weights (0..1)  < 0.02        : 0
        faces with volume ratio of neighbour cells < 0.01      : 0
        faces with face twist < 0.02                           : 20
        faces on cells with determinant < 0.001                : 1861547
      <<Writing 1861567 faces in error to set meshQualityFaces

    Failed 2 mesh checks.

    End

            6.86 real         5.82 user         0.36 sys
              1475723264  maximum resident set size
                       0  average shared memory size
                       0  average unshared data size
                       0  average unshared stack size
                  110353  page reclaims
                     123  page faults
                       0  swaps
                       0  block input operations
                       0  block output operations
                       0  messages sent
                       0  messages received
                       0  signals received
                      12  voluntary context switches
                    6487  involuntary context switches
            126939236869  instructions retired
             23575036254  cycles elapsed
              1420183184  peak memory footprint
