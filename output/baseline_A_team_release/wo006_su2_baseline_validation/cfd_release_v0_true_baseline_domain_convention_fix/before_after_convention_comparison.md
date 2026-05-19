# Before / After Convention Comparison

- previous: `{'CD_primary': 0.01837651, 'CD_total': 0.06993191, 'CL_primary': 0.5654834, 'diagnostic_fraction_of_total': 0.7372226718818348, 'yplus_max': 2.8138, 'yplus_mean': 0.5882082748397414, 'yplus_p95': 1.17049}`
- corrected: `{'CD_primary': 1.889339, 'CD_total': 1.921214, 'CL_primary': 6.774819, 'diagnostic_fraction_of_total': 0.016591258964383977, 'diagnostic_sum_excluding_root': 0.031875359, 'force_stable': False, 'yplus_max': None, 'yplus_mean': None, 'yplus_p95': None}`
- delta: `{'CD_primary_change': 1.8709624900000001, 'CD_total_change': 1.85128209, 'CL_primary_change': 6.2093356}`

- corrected coefficient values are unstable last-attempt diagnostics, not accepted aerodynamic coefficients.
- CD_total changed because the root plane is no longer a noSlip wall and half-wing forces use half-wing Sref.
- Diagnostic root contamination is removed from forceCoeffs.
- CD_primary should be judged under the corrected half-Sref convention, not against the previous full-Sref half-domain number.
- yPlus remains wall-resolved-like if the corrected yPlus mean/p95 stay below 5/10.
- ready for AoA/CL sweep: `False`
