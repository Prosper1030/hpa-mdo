# Prior Failure Reinterpretation

The previous true-Baseline single-surface inflated structured-hexa route failed
before solver use.  The best recorded debug family still contained negative or
zero-volume cells, max non-orthogonality around `170 deg`, and max skewness above
`1000` in a checkMesh run; the final custom-quality attempt still had hundreds
of non-positive cells.  The user-reported best attempt `b6_span24` also had
`max_skew approx 604`, `max_non_orth approx 150 deg`, and `neg_skin approx 1.3%`.

Span/chord aspect ratio alone is not enough to explain that failure.  High aspect
ratio cells can be acceptable when they are aligned with spanwise flow/geometry
and have sane face interpolation.  The observed failure mode was not merely long
cells: it included negative volumes, extreme non-orthogonality, and skewness
localized by the old route near global morph/taper/twist mappings, sharp TE
handling, perimeter cells, and tip/closure ownership.

The next architecture is therefore station-wise: build a clean 2D O-grid in each
local airfoil section frame, transform each section by the station chord, twist,
dihedral, and placement, then connect only adjacent stations bay-by-bay.  This
keeps high aspect ratio where it is aligned and prevents one global inflated-body
mapping from dragging cells across taper, twist, dihedral, and airfoil morph zones.
