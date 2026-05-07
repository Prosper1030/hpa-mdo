# Suspected Wiring Bugs

| Check | Evidence | Current assessment |
|---|---|---|
| Wrong Cm sign | Sign flip changes residual from `1707.2` to `1316.9` N*m but does not pass. | Possible sign convention issue, not the only cause. |
| Wrong moment arm | Rear spar x-shift variants move the residual only modestly. | Not primary. |
| Aerodynamic section z vs beam-line z | Force closure passes and z-shape inverse is feasible; this failure is in moment resultants, not z recovery. | No direct evidence as primary cause. |
| Stale spanload / old blackcat load | The case rebuilds from Phase 13 smooth candidate artifacts and selected recipe id matches. | Unlikely for this failure. |
| Unit mismatch | Residual scales with torque on/off and not by 1000x or 2x. | No obvious mm/m or half/full-span signature. |
| Full-span vs half-span factor | Force closure is near zero and mass convention is unrelated to moment residual. | Unlikely. |
| Front/rear spar swapped | Stiffness/position changes do not resolve closure. | Unlikely as sole cause. |
| Reaction point-moment sign | Postprocess +reaction moments changes residual to `1523.3` N*m. | Sign convention affects result but is insufficient alone. |
| Constraint Mz suppression | Including raw constraint Mz changes residual to `1098.5` N*m. | Current yaw closure channel is inconsistent/report-only. |
| Moment closure connected to selector | Phase 13 now exposes it correctly as `production_hard_feasible=False`. | Selector wiring fixed; physics diagnostic still unresolved. |
