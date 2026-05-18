# Route Smoke Report

- status: `route_smoke_pass`
- simpleFoam ran: `True`
- dry-run passed: `True`
- yPlus postprocess passed: `True`
- CD_primary: `0.01837651`
- CL_primary: `0.5654834`
- CD_total: `0.06993191`
- domain y extent: `[0.0, 17.166143]` m
- patch-geometry audit: tip_left is exactly y=0 plane while tip_right is y=17.166143 plane; this looks like a half-span/root-symmetry domain, not a +/- full-span wing.
- checkMesh: rc `0`, elapsed_s `3.702268334105611`
- simpleFoam_dry_run: rc `0`, elapsed_s `1.2961642076261342`
- simpleFoam_200: rc `0`, elapsed_s `754.71`
- simpleFoam_500: rc `0`, elapsed_s `747.38`
- postProcess_yPlus: rc `0`, elapsed_s `3.83`
