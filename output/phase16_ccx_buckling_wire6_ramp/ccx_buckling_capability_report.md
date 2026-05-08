# CalculiX Buckling Capability Report

## What Was Proved

- Status: `PASS`
- Message: CalculiX BUCKLE completed and matched the installed verification reference.
- Case: `beamb`
- Solver: `/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23`
- Source INP: `/opt/homebrew/share/calculix-ccx/beamb.inp`
- Reference DAT: `/opt/homebrew/share/calculix-ccx/beamb.dat.ref`
- Deck: `/Volumes/Samsung SSD/hpa-mdo/output/phase16_ccx_buckling_wire6_ramp/_ccx_buckle_runtime/beamb.inp`
- Log: `/Volumes/Samsung SSD/hpa-mdo/output/phase16_ccx_buckling_wire6_ramp/_ccx_buckle_runtime/beamb.log`
- DAT: `/Volumes/Samsung SSD/hpa-mdo/output/phase16_ccx_buckling_wire6_ramp/_ccx_buckle_runtime/beamb.dat`
- FRD: `/Volumes/Samsung SSD/hpa-mdo/output/phase16_ccx_buckling_wire6_ramp/_ccx_buckle_runtime/beamb.frd`

## Benchmark

- Model: installed CalculiX verification example `beamb`, a compressed beam/solid buckling case.
- Check: local `ccx_2.23` BUCKLE eigenvalues compared against the installed `beamb.dat.ref` reference table.
- lambda_1: `48.1546`
- reference lambda_1: `48.1546`
- Max eigenvalue table error: `0%`
- Parsed eigenvalues: `10`

## Engineering Meaning

- This proves the local ccx executable can run a real eigen-buckling solve and return a physical buckling factor.
- It does not by itself certify the HPA candidate tube wall, ovalization, joints, ribs, or wire fittings.
- The next FEM step for the candidate is to use this proven `*BUCKLE` route on a candidate-specific shell/detail model, not to treat the old B32R pipe route as final local-wall truth.
