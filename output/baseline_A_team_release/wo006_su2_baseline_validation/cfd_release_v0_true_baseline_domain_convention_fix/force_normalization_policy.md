# Force Normalization Policy

- Mesh convention: `half-wing`.
- Full-wing authority Sref: `33.420059598` m^2.
- Corrected half-wing Sref: `16.710029799` m^2.
- `forceCoeffs` uses the half-wing Sref because the solved domain is the half-wing.
- Raw half-domain coefficients are therefore also full-wing-equivalent under mirror symmetry:
  `C = F_half / (q * S_half) = (2 F_half) / (q * S_full)`.
- Root symmetry is a computational plane and contributes no aerodynamic force.
- Physical diagnostic force groups include only `physical_tip` and `te_wall` unless a closure wall appears.
