# WO-006 Fine Same-Mesh CFD Architecture Sensitivity

Short verdict from serial RAM-safe OpenFOAM probes on the accepted Fine mesh.

## 2026-08-02 Bounded Recovery Completion

Final verdict: `transition_route_not_established`.

The LM r2 and fully turbulent SST cases were each extended to 100 finite,
contiguous force rows. LM fails the CD/CL/CmPitch gate at
`10.699%/1.467%/0.012387`; SST fails at
`15.705%/2.382%/0.015438`. Both retained full-volume finite fields, but LM `k`
mean grows 52.4% and SST 63.4% from 2075 to 2100. Primary-wall yPlus is
acceptable, so the blocker is the evolving steady turbulence/force state, not
missing rows or first-layer resolution. SST is not a stable upper bracket and
must not warm-start LM. No endpoint coefficient or design-power update is
authorized.

The compact recovery authority, including all six attempts, force rows, field
ranges, warnings, dictionaries, mesh hashes and engineering interpretation, is
`../cfd_release_v0_hpa_openfoam_transition_baseline_recovery/`. The 50-row
table below is retained as pre-recovery provenance and is superseded by that
package.

## Key Results

| case | status | CD_pressure | CD_viscous | CD_total | CL | note |
|---|---:|---:|---:|---:|---:|---|
| SA outlet fixedValue p=0 | 5-row repeatability control; insufficient window | 0.022945 | 0.010316 | 0.033261 | 1.1610 | matches accepted Fine locally |
| SA outlet freestreamPressure | 5-row repeatability control; insufficient window | 0.022945 | 0.010316 | 0.033261 | 1.1610 | indistinguishable from fixedValue locally |
| SA outlet zeroGradient+pRef | 50 rows; insufficient window | 0.022856 | 0.010318 | 0.033174 | 1.1636 | pressure change about -0.00009 mean, below 0.002 gate |
| SST Tu0.5 L=0.001c | 100 rows; unstable | 0.024778 | 0.006713 | 0.031491 | 1.1698 | means are not qualified; CD span 15.705% and fields grow |
| LM r1 Tu0.5 L=0.001c | 50 rows; insufficient window | 0.022490 | 0.008039 | 0.030529 | 1.1616 | omega bounded but no catastrophic blow-up |
| LM r2 conservative/upwind | 100 rows; unstable | 0.023304 | 0.007573 | 0.030877 | 1.1645 | means are not qualified; CD span 10.699% and component cancellation grows |
| pimple SST | invalid | - | - | - | - | process exited without advancing to a force history |

Values are diagnostic means over the available rows. SST and LM r2 now have the
required row count but fail stability; the remaining historical sensitivity
rows still have insufficient windows.

## 2026-08-02 Evidence Requalification

The runner now requires at least 100 unique force rows, CD/CL relative span
below 1%, CmPitch absolute span below 0.005, positive time advance and a real
force history. It also writes resumable steady checkpoints, defaults to serial,
guards process-tree RSS, and uses external-SSD scratch. Existing coefficients
did not change; their qualification labels did.

## Engineering Decision

- Outlet pressure setting is not the CD=0.0333 root cause. `freestreamPressure` is identical to fixed p=0; `zeroGradient+pRef` changes pressure drag by far less than 0.002.
- The early SST/LM rows were lower than SA mainly through viscous drag, but the
  completed windows show pressure rising while viscous drag falls. This is
  unstable component cancellation, not a qualified CD reduction.
- Neither current model explains the pressure residual. LM last-25 mean
  `CDp=0.025544` and SST `0.027928`, both above accepted SA
  `CDp=0.022950`.
- The attempted same-mesh `pimpleFoam` case is not a result: it produced no force history. Its preflight Courant number was about 1.28e5 at `deltaT=0.02`, implying `deltaT≈1.6e-7 s` for `maxCo≈1`.
- Do not update design power. Use current SA/Fine only as a high-drag warning;
  do not run another identical continuation. First bound the real turbulence
  environment and validate the low-Re model and tip/outer-wing behavior against
  simpler or measured evidence.
