# Engineering Decision Notes

## Why Policy A Is Performance-Best But Archive-Caveated

Policy A has the better estimated profile-drag result in the studied sidecar set: profile Cd `0.010995` and CD0 estimate `0.014884`, versus Policy C profile Cd `0.011398` and CD0 estimate `0.015288`. It also has essentially the same span-efficiency level. Under actual-sidecar query grading, all four zones pass.

The caveat is that DAE11 root/mid1 still carries the record-level archive label `full_polar_candidate_not_mission_grade` because the archive grading envelope was intentionally broader and demanded more Cl margin than the actual sidecar operating point.

## Why Policy C Is The Conservative Reporting Baseline

Policy C is the only clean conservative baseline among the two main candidates: CST root/mid1 plus ClarkY outer sections pass both `archive_source_quality` and `actual_sidecar_query_quality`. That makes it better for external reporting or any result that should not depend on accepting actual-envelope regrading policy.

## Why The Two Quality Labels Differ

The archive label is record-level and envelope-level: it asks whether the full-polar record has robust coverage and margin for a conservative zone envelope. The actual-sidecar label is query-level: it asks whether this exact AVL sidecar assignment, at its actual station Re/Cl work points, can be queried safely without extrapolation or record-quality blockers.

## Why DAE11 Passes Actual Demand But Fails Archive Grading

DAE11 safe_clmax is about `1.485677`. The actual Policy A root/mid1 Cl maxima are `1.326623` and `1.344053`, so the actual margins are positive. The archive envelope used a higher root/mid1 requirement, about `1.56`, which exceeds DAE11 safe_clmax. That is a conservative envelope mismatch, not proof that DAE11 is physically poor at the current operating point.
