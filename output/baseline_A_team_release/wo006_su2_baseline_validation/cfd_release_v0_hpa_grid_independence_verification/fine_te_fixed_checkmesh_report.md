# Fine TE-Fixed CheckMesh Report (Phase 3)

Verdict: `lower-TE face-pyramid blocker removed; inherited meshQuality warning remains`

The Fine mesh was regenerated from the modified C-grid generator. No polyMesh
vertex shifting, `removeFaces`, or hand repair was used.

## Build Basis

| item | value |
|---|---:|
| scale | `1.25` |
| half-wing span cells | `95` |
| `n_perim` | `240` |
| `n_radial` | `80` |
| wake cross cells | `4` |
| first layer height | `5.0e-5 m` |
| half-wing cells | `1,854,400` |
| full-wing mirror cells | `3,708,800` |

Artifact:
`fine_te_radial_chord_shift_run/openfoam_cases/fine/fullwing_artificial_tip_symmetry/`

## Patch Roles

Patch names and roles stayed on the accepted OpenFOAM mirror-route contract:

| patch | faces | type / role |
|---|---:|---|
| `airfoil_upper` | `22800` | wall |
| `airfoil_lower` | `22800` | wall |
| `te_wall` | `760` | wall |
| `outlet` | `760` | patch |
| `farfield` | `45600` | patch |
| `physical_tip_right` | `19520` | symmetry-plane policy in solver setup |
| `physical_tip_left` | `19520` | symmetry-plane policy in solver setup |

## Full-Wing `checkMesh -meshQuality`

Command log:
`fine_te_radial_chord_shift_run/openfoam_cases/fine/fullwing_artificial_tip_symmetry/log.checkMesh`

Key output:

```text
points: 3774924
faces: 11192280
internal faces: 11060520
cells: 3708800
Boundary openness OK.
Max cell openness = 4.98214e-14 OK.
Min volume = 7.77078e-10. Max volume = 1.90828. Cell volumes OK.
Mesh non-orthogonality Max: 87.516 average: 25.5065
Face pyramids OK.
Max skewness = 3.46221 OK.
faces with face pyramid volume < 1e-18: 0
faces with face twist < 0.02: 10
faces on cells with determinant < 0.001: 2266249
Failed 1 mesh checks.
```

## Acceptance Gates

| gate | result | status |
|---|---:|---|
| open cells | `0` | pass |
| negative volumes | `0` | pass |
| wrong-oriented face pyramids | `0` | pass |
| face pyramid volume `< 1e-18` | `0` | pass |
| max non-orthogonality | `87.516 deg` | pass |
| max skewness | `3.46221` | pass |
| checkMesh return code | `0` | pass |
| strict `meshQuality` failed-check count | `1` | warning |

The original Phase 1 blocker was wrong-oriented lower-TE body/wake face
pyramids. That blocker is gone. The remaining failed check is the inherited
structured-BL low-determinant / face-twist warning also seen on the accepted
route-smoke family. It is not a new lower-TE sliver failure, but it is still a
mesh-quality trust-boundary item for final CFD qualification.

## Engineering Read

The Fine mesh is now good enough to attempt the bounded solver smoke under the
existing project gate, because the hard topology blockers are gone: no open
cells, no negative volumes, and no wrong-oriented face pyramids. It is not a
clean final validation mesh: the determinant/twist warning must stay visible in
any downstream interpretation.
