# B5 Single-Beam Torsion Probe

## Probe Summary

| Case | Applied tip MY [N m] | |UZ_tip| [m] | Root section torque [N m] | Tip section torque [N m] | Max |torque| [N m] |
| --- | ---: | ---: | ---: | ---: | ---: |
| single_tip_my_100nm | 100.000 | 3.211820e-10 | 99.999 | 100.120 | 100.120 |
| single_control_0nm | 0.000 | 0.000000e+00 | 0.000 | 0.000 | 0.000 |

## Engineering Interpretation

- With a pure 100 N m tip `MY` load, the centerline `UZ` response stays tiny (3.212e-10 m), so the old B5 `UZ`-only route is structurally blind to pure torsion on a centered single beam.
- The same deck shows a clean `SECTION FORCES` torque signal: root/tip values 99.999 / 100.120 N m and max |torque| 100.120 N m.
- The zero-torque control stays at 0.000e+00 N m, so the signal is not numerical noise from the parser alone.

## Verdict

CalculiX does expose beam-axis torsion in this benchmark family. The missing piece was not solver capability; it was that the prior parity report was watching the wrong observable.
