# Medium to Fine Grid Convergence Report (Phase 5)

Verdict: `Medium-to-Fine grid convergence cannot be evaluated`

The lower-TE generator fix removed the Fine mesh's wrong-oriented face-pyramid
blocker, but the Fine solver did not produce a stable force window. Therefore
the Medium/reference to Fine comparison remains blocked.

## Medium / Reference State

Accepted route-smoke basis:

| quantity | value |
|---|---:|
| cells | `1,996,800` |
| CD_primary | `0.03276165` |
| CL_primary | `1.133291` |
| CD_total | `0.05708291` |
| y+ mean | `0.5678595` |
| y+ p95 | `1.0904245` |
| y+ max | `2.65697` |
| force window | stable |

This remains a valid route-smoke reference, not a grid-independent design value.

## Fine State After TE Generator Fix

| gate | value |
|---|---|
| open cells | `0` |
| negative volumes | `0` |
| wrong-oriented face pyramids | `0` |
| checkMesh return code | `0` |
| remaining meshQuality warning | `Failed 1 mesh checks` from inherited determinant/twist flags |
| solver status | `runaway_guard_triggered` at pseudo-time `1` |
| qualified y+ | unavailable |

Invalid first-row Fine force values:

| group | CD | CL |
|---|---:|---:|
| primary | `3.950888` | `7.796553` |
| total_physical | `3.954488` | `7.796247` |

These values are not a grid-convergence point.

## Required Criteria

| criterion | status |
|---|---|
| CL Medium->Fine `< 1%` | not evaluated |
| CD Medium->Fine `< 2-3%` preferred | not evaluated |
| CD change `> 5%` means not grid-independent | Fine invalid before comparison |
| y+ remains acceptable | Fine y+ unavailable |
| force window stable | fail |
| Cp/Cf comparison | unavailable |
| wake / tip-vortex indicators | unavailable |

## Engineering Read

Do not compute a meaningful percent delta from the Fine first-row values. The
solver stopped because the force magnitudes were already nonphysical. The next
blocker is now Fine solver stability / initialization / numerical setup on the
TE-fixed mesh family, not the lower-TE generator face-pyramid defect.
