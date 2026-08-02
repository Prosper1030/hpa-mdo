# WO-006 OpenFOAM Transition Baseline Recovery

## Verdict

`transition_route_not_established`

Neither the Langtry-Menter lane nor the fully turbulent SST fallback produced
the required stable 100-row force window. Both lanes completed serially within
the RAM/disk controls, retained finite full-volume fields, and had acceptable
primary-wall yPlus, but their force components and turbulence state continued
to evolve materially. Therefore no LM or SST coefficient in this package is a
qualified HPA drag value. The accepted SA/Fine result remains a grid-stable
high-drag warning, not low-Re drag truth.

## Locked basis and provenance

- OpenFOAM OpenCFD v2512 `simpleFoam`, serial only, accepted Fine full-wing
  mesh: 6,090,240 cells.
- Candidate and accepted Fine `boundary/points/faces/owner/neighbour` SHA-256
  sets match exactly; see each `configuration_manifest.json`.
- `rho=1.225 kg/m^3`, `V=6.5 m/s`, `nu=1.4607e-5 m^2/s`,
  `AoA=0.18 deg`, `Sref=33.420059598 m^2`, `Cref=1.003721543 m`.
- Identical legacy `total_physical` force basis: `airfoil_upper`,
  `airfoil_lower`, `te_wall`; tip/side closure patches named
  `physical_tip_left/right` are excluded from direct force, exactly as in the
  accepted SA comparison.
- Accepted same-basis SA/Fine reference: `CD_pressure=0.0229500141`,
  `CD_viscous=0.0103155482`, `CD_total=0.03326556`, `CL=1.160927`,
  `CmPitch=-0.1322138`.
- Phase J's `33 C / 80%RH` environment is deliberately deferred. This package
  does not mix it into the locked diagnostic basis and a later same-model
  environment sensitivity is required only after a stable method exists.

## Force-window evidence

The case means and endpoints below are reported to diagnose drift, not promoted
as coefficients.

| lane / statistic | CD pressure | CD viscous | CD total | CL | CmPitch |
|---|---:|---:|---:|---:|---:|
| accepted SA/Fine | 0.0229500 | 0.0103155 | 0.0332656 | 1.160927 | -0.132214 |
| LM final-100 mean | 0.0233039 | 0.0075731 | 0.0308770 | 1.164523 | -0.136862 |
| LM row 2100 | 0.0267965 | 0.0057946 | 0.0325911 | 1.175940 | -0.144041 |
| SST final-100 mean | 0.0247780 | 0.0067132 | 0.0314912 | 1.169804 | -0.139689 |
| SST row 2100 | 0.0288513 | 0.0059236 | 0.0347749 | 1.185850 | -0.147131 |

Formal gate requirements are CD and CL relative spans below 1% and CmPitch
absolute span below 0.005. LM instead has `10.699%`, `1.467%`, and `0.012387`;
SST has `15.705%`, `2.382%`, and `0.015438`. All 100 rows in each lane are
finite, unique, contiguous from 2001 through 2100, close component force to
within `1e-7 CD`, and reach the latest checkpoint. Failing the gate is physical
and numerical drift, not missing rows.

The component split is especially disqualifying. LM first-25 to last-25 means
move from `CDp 0.022054 -> 0.025544` while `CDv 0.009475 -> 0.006086`;
the nearly unchanged total over those subwindows is cancellation. SST moves
from `CDp 0.022068 -> 0.027928` and `CDv 0.008767 -> 0.005735`, while total CD
rises `0.030835 -> 0.033664`. Within SST's final 25 rows, even the viscous term
has reversed upward: per-iteration slopes are `+8.081e-5` pressure,
`+1.340e-5` viscous and `+9.421e-5` total. A low transient total CD cannot be
selected from either trajectory.

## Field, residual and warning evidence

All required saved fields contain exactly 6,090,240 finite internal values.
Finiteness is necessary but not stability:

- LM 2075-to-2100 `k` mean grows `0.002536 -> 0.003865` (+52.4%) and maximum
  `0.323978 -> 0.509640` (+57.3%); `nut` mean grows 9.94%. The two chunks emit
  100 `maxLambdaIter` correlation warnings and 102 `k` bounding messages.
  `ReThetat` minimum drops `296.453 -> 240.072`.
- SST 2075-to-2100 `k` mean grows `0.017002 -> 0.027782` (+63.4%) and maximum
  `0.473225 -> 0.750573` (+58.6%); `nut` mean grows 24.2% and maximum 32.8%.
  The two chunks emit 102 `k` and 81 `omega` bounding messages.
- Every solver log terminates normally and contains finite residual/continuity
  values; this does not mean warning-free or qualified.
  In the second chunks, maximum final linear residual is `1.52e-4` for LM and
  `7.86e-5` for SST; maximum absolute global continuity error is `2.48e-7` and
  `2.10e-7`, respectively. Small linear residuals do not override the evolving
  nonlinear turbulence and force state.

## yPlus and transition interpretation

| lane | patch | mean | max | faces below 1 | below 5 | above 20 |
|---|---|---:|---:|---:|---:|---:|
| LM | upper | 0.630 | 2.401 | 81.42% | 100% | 0% |
| LM | lower | 0.657 | 2.885 | 93.15% | 100% | 0% |
| SST | upper | 0.683 | 2.353 | 76.24% | 100% | 0% |
| SST | lower | 0.643 | 2.829 | 93.16% | 100% | 0% |

Thus primary near-wall resolution is not the reason for rejection. However,
the excluded tip/side closure patches named `physical_tip_left/right` are not
benign numerical walls: final SST yPlus mean is about 109 and maximum 411. They
do not enter the locked direct force sum, but they still influence the flow, so
the result is only an identical-basis comparison and not an independently
complete physical-wing force definition.

The LM wall-owner audit has 200 upper/lower span-chord bins. On the upper
surface, 86 bins have mean `gammaInt<0.1` and 14 are intermittent; all 100 lower
bins have mean below 0.1. No bin even has `gammaInt max>0.9`. This demonstrates
that the code evolved laminar/intermittent regions, but it does not establish a
plausible completed transition pattern. The field is still changing, force is
not stable, the freestream inputs are unmeasured, first-order scalar convection
is a stabilization sensitivity, and the installed standard LM model lacks the
stationary-crossflow extension relevant to a swept wing.

## Engineering decision

The turbulence-model change does not explain away the SA pressure-drag excess.
Both candidates begin near the SA pressure term, then their last-25 pressure
means climb above it while viscous drag falls. The apparent early total-drag
reduction is model-state cancellation, not a qualified removal of distributed
pressure drag.

No third identical LM/SST chunk is justified: two successive 50-step chunks
already provide the requested 100-row observation window and two retained
checkpoints show accelerating field growth. More Fine iterations would violate
the work order's no-brute-force intent. SST is not qualified, so SST-to-LM warm
start is explicitly rejected.

At `98.5 kg`, level lift on this locked sea-level basis would require roughly
`CL=1.11691`; accepted SA/Fine is about 3.94% higher at the fixed AoA. This is
another reason not to treat any fixed-AoA row as mission-trim truth. No mass,
geometry, procurement or design-power value is changed.

The next credible action is not another identical Fine continuation. First
bound the actual free-flight turbulence/roughness environment and independently
validate low-Re SST/LM and tip/outer-wing boundary behavior against a simpler
benchmark or measured evidence. Only then authorize a purpose-built numerical
route; perform the `33 C / 80%RH` same-model sensitivity after that route is
stable.

## Resource closure

- 16-GB Mac, serial `--np 1`; one solver process at a time.
- Four actual 50-iteration chunks: 4960.224 s total (82.670 min).
- Campaign peak process-tree RSS: 8,245,035,008 bytes (8.245 GB decimal), below
  the 10-GB guard; no memory-guard stop.
- Solver-visible scratch: `/Volumes/hpa-cfd-tmp/architecture_sensitivity` on a
  64-GiB APFS sparsebundle physically backed at
  `/Volumes/Samsung SSD/hpa-cfd-tmp/architecture_sensitivity/`.
- Minimum recorded pre-solve free space was 66,583,343,104 bytes, above the
  20-GB gate. Scratch case data was removed after copy-back. System `/tmp` was
  never used.

Exact force rows, gates, field ranges, yPlus, transition bins, dictionary
snapshots/diffs, mesh hashes, log summaries and SA comparisons live beside this
report and in `sst_fully_turbulent/`.
