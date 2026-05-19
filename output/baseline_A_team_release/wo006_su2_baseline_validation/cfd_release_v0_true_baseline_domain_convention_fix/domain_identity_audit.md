# Domain Identity Audit

- mesh identity: `half-wing`
- y range: `0.0..17.166143` m
- y span: `17.166143` m
- current authority half/full span: `17.166143` / `34.332286` m
- patch on y=0: `tip_left`
- outboard span patch: `tip_right`
- previous Sref in forceCoeffs: `33.420059598` m^2
- corrected Sref in forceCoeffs: `16.710029799` m^2
- coefficient correction: previous half-domain forces used full-wing Sref, so same-force coefficients were about half of the corrected half-Sref convention

| patch | y min | y max | x min/max | z min/max |
|---|---:|---:|---|---|
| `airfoil_upper` | `0.0` | `17.166143` | `[0.00036017201672, 1.25193741663]` | `[-0.0953710003071, 2.68911623532]` |
| `airfoil_lower` | `0.0` | `17.166143` | `[0.00036017201672, 1.25191195517]` | `[-0.0956054999562, 2.63933242922]` |
| `te_wall` | `0.0` | `17.166143` | `[0.643886881713, 1.25193741663]` | `[-0.0956054999562, 2.59679425093]` |
| `outlet` | `0.0` | `17.166143` | `[5.36156842058, 12.5274660009]` | `[-13.6170242982, 11.3891466859]` |
| `farfield` | `0.0` | `17.166143` | `[-12.5353211061, 12.5274660009]` | `[-13.6170242982, 11.6207953958]` |
| `tip_left` | `0.0` | `0.0` | `[-12.5353211061, 12.5274660009]` | `[-13.6170242982, 11.6207953958]` |
| `tip_right` | `17.166143` | `17.166143` | `[-6.44282440267, 6.2232931583]` | `[-4.18407772211, 8.73898634174]` |
