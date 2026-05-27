# WO-006 Fine Same-Mesh CFD Architecture Sensitivity

Short verdict from serial RAM-safe OpenFOAM probes on the accepted Fine mesh.

## Key Results

| case | status | CD_pressure | CD_viscous | CD_total | CL | note |
|---|---:|---:|---:|---:|---:|---|
| SA outlet fixedValue p=0 | stable 5-step control | 0.022945 | 0.010316 | 0.033261 | 1.1610 | matches accepted Fine |
| SA outlet freestreamPressure | stable 5-step | 0.022945 | 0.010316 | 0.033261 | 1.1610 | indistinguishable from fixedValue |
| SA outlet zeroGradient+pRef | not force-window stable to 2050 | 0.022856 | 0.010318 | 0.033174 | 1.1636 | pressure change about -0.00009 mean, below 0.002 gate |
| SST Tu0.5 L=0.001c | not force-window stable to 2050 | 0.022740 | 0.007694 | 0.030434 | 1.1625 | total drops about 0.0028 mean, mainly viscous/turbulence state |
| LM r1 Tu0.5 L=0.001c | not force-window stable to 2050 | 0.022490 | 0.008039 | 0.030529 | 1.1616 | omega bounded but no catastrophic blow-up |
| LM r2 conservative/upwind | not force-window stable to 2050 | 0.022179 | 0.008688 | 0.030866 | 1.1607 | no omega bounding in first 50 iterations; best LM setup tried |

Values are final-window means except the SA fixed/freestream 5-step controls.

## Engineering Decision

- Outlet pressure setting is not the CD=0.0333 root cause. `freestreamPressure` is identical to fixed p=0; `zeroGradient+pRef` changes pressure drag by far less than 0.002.
- SA is higher than SST/LM by about 0.0024-0.0034 CD in these probes, but SST/LM do not bring CD near 0.022.
- The pressure component remains around 0.0222-0.0229 in the best steady probes; the model bracket mostly changes viscous/turbulent state and wake relaxation, not the whole pressure residual.
- Same-mesh physical `pimpleFoam` is not a practical minimal test on this Fine BL mesh: at `deltaT=0.02`, max Courant is about 1.28e5, implying `deltaT≈1.6e-7 s` for `maxCo≈1`.
- Do not update design power. Use current SA/Fine only as a high-drag warning; the next credible baseline route is longer bounded SST/LM steady continuation or a purpose-built transient/wake setup, not same-mesh physical URANS on this mesh.
