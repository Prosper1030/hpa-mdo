# Explanation: Why DAE/ClarkY Beat CST In The Full-Polar Sidecar

## Short Answer

The current full-polar sidecar behavior is mostly a low-actual-Cl profile-drag outcome, with a quality-label effect at the tip. Mid2 and tip are underloaded relative to the Fourier target, so the selected outer airfoils are being judged around actual Cl values near `0.670381` for mid2 and p90 `0.467074` for tip. At those work points ClarkY has the lowest profile Cd among the eligible seed/DAE/CST options and is full-polar mission-grade for the query.

This does not prove ClarkY is the right final HPA outer airfoil. It says the present AVL-loaded shape is underusing the outer wing, and the sidecar is optimizing profile drag at that underloaded operating point.

## Why ClarkY Was Selected For Mid2 And Tip

Mid2:

- Best seed/DAE: `clarkysm`, mean_cd `0.007935`, cd_p90 `0.007935`, stall margin `6.235869`, quality `mission_grade_sidecar`.
- Best CST: `cst_mid2_nsga2_g04_child_0024_0b55bfc3`, mean_cd `0.009276`, cd_p90 `0.009276`, stall margin `5.321417`, quality `mission_grade_sidecar`.
- CST-minus-seed mean_cd delta: `0.001341`.

Mid2 was not a CST-quality failure: the best mid2 CST is mission-grade. ClarkY won because it has lower Cd at the current actual Cl, and the actual Cl is low enough that its stall margin is very large.

Tip:

- Best seed/DAE: `clarkysm`, mean_cd `0.008873`, cd_p90 `0.008433`, stall margin `8.060334`, quality `mission_grade_sidecar`.
- Best CST: `cst_tip_nsga2_g02_child_0085_cb99bc9c`, mean_cd `0.009421`, cd_p90 `0.008952`, stall margin `7.255116`, quality `not_mission_grade_sidecar`.
- CST-minus-seed mean_cd delta: `0.000549`.

Tip is both a low-Cl effect and a quality effect. ClarkY is lower Cd at the current actual Cl, while the best CST tip candidates in this full-polar archive are not mission-grade. DAE31 is record-level full-polar mission-grade, but at the current tip Cl it receives a query warning and is demoted at sidecar-query level.

## Policy Takeaways

- Policy A selected `root:dae11|mid1:dae11|mid2:clarkysm|tip:clarkysm` with profile_cd `0.010995` and e_CDi `0.985693`.
- Policy B, CST-only, selected `root:cst_root_nsga2_g05_child_0019_00cc4dca|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:cst_mid2_nsga2_g04_child_0024_0b55bfc3|tip:cst_tip_nsga2_g02_child_0085_cb99bc9c`. Its profile_cd is `0.012108`, higher than Policy A, and its band is `target`.
- Policy C, full-polar mission-grade only, selected `root:cst_root_nsga2_g05_child_0019_00cc4dca|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:clarkysm|tip:clarkysm`. It still keeps ClarkY available, so it does not force a CST outer wing.
- Policy D, no ClarkY, selected `root:cst_root_nsga2_g05_child_0019_00cc4dca|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:dae31|tip:dae41`. It gets the best e_CDi/RMS pair in this shortlist, but remains not-mission-grade because DAE41 is not mission-grade.
- Policy E, no DAE, selected `root:cst_root_nsga2_g05_child_0019_00cc4dca|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:clarkysm|tip:clarkysm`. This shows DAE removal alone does not remove ClarkY; ClarkY remains the low-Cl outer-wing winner.

## Tip Forced To DAE31

Forcing the Policy A winner's tip to DAE31 gives `root:dae11|mid1:dae11|mid2:clarkysm|tip:dae31`. The result is profile_cd `0.01188`, CD0_total_est `0.01577`, e_CDi `0.932308`, and source_quality `not_mission_grade_sidecar`. The important detail is not stall margin; DAE31 has plenty of stall margin here. The problem is that the current tip actual Cl is so low that DAE31 is evaluated outside or near the low-Cl edge of its useful full-polar coverage, so profile Cd gets worse.

## Engineering Read

The sidecar is doing what it was asked to do, but the engineering premise is suspicious: outer actual Cl is far below the Fourier target. Selecting ClarkY may be a symptom of the current loaded-shape mismatch rather than a robust airfoil conclusion. Before changing hard gates or ranking, the next engineering check should be whether the spanload/twist route can bring mid2/tip actual Cl closer to target; if that happens, the CST and DAE rankings may change materially.
