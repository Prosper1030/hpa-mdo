# CST Discontinuous-Cd Audit

## Detection Rule

The archive builder marks `discontinuous_cd` when any finite, converged Re plus roughness alpha sweep has an adjacent Cd jump greater than `0.08`. This audit does not relabel archive quality; it diagnoses whether those failures look like true airfoil physics or polar-processing/XFOIL artifacts.

- Failed CST candidates inspected: `18`
- Repair-worthy candidates identified: `7`
- Cause categories: `{'likely_sparse_alpha_grid_or_branch_issue_near_design_cl': 14, 'likely_XFOIL_branch_post_stall_issue': 3, 'likely_sparse_alpha_grid_issue': 1}`
- Main-design-branch risk: `{'medium_near_cl_but_not_clear_main_branch': 17, 'low_far_from_design_cl': 1}`

## Main Pattern

Most discontinuities occur in clean sweeps near high-alpha stall, post-stall, or across an effective alpha gap caused by missing/nonconverged adjacent points. That points more toward XFOIL branch/post-stall handling or effective sparse-grid behavior than toward a simple actual Cl/Re envelope problem.

Several jumps numerically overlap the operating-Cl range, so they are not safe to promote blindly. However, most of those overlaps are not clearly on the main actual-query branch because they occur across a high-alpha branch switch or effective alpha gap. Those are repair-worthy diagnostics, not automatic upgrades.

No CST case in this audit is cleanly classified as roughness-only, nonphysical geometry, or definite true airfoil physics. The evidence is strongest for XFOIL branch/post-stall behavior plus effective sparse-grid gaps from missing/nonconverged neighboring alpha points.

## Repair-Worthy Rule

A CST candidate is marked repair-worthy only when it is otherwise competitive at actual sidecar work points, has positive safe-Cl margin, fails actual query grading only through `cd_discontinuity`, and the trigger is not clearly on the main design branch. This is a repair priority label, not a quality upgrade.

## Failed CST Cases

| airfoil_id | zone | mean_cd | cd_p90 | safe_clmax | stall_margin_cl | trigger_region | design_proximity | main_design_branch_risk | cause_category | would_otherwise_be_competitive | repair_worthy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cst_mid1_nsga2_g06_child_0004_623ed74b | mid1 | 0.0168749814 | 0.017089893 | 1.64640818 | 0.270127416 | Re=200000, clean, alpha 15.00->16.00, Cl 1.678->1.080, Cd 0.0590->0.1847 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_mid1_nsga2_g06_child_0046_9ca15362 | mid1 | 0.0179760484 | 0.0181988854 | 1.67892842 | 0.302647658 | Re=150000, clean, alpha 13.00->13.50, Cl 1.708->1.055, Cd 0.0468->0.1638 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_XFOIL_branch_post_stall_issue | False | False |
| cst_mid1_nsga2_g07_child_0120_6ba170d3 | mid1 | 0.0170504457 | 0.0172725125 | 1.65707 | 0.280789236 | Re=150000, clean, alpha 9.00->12.00, Cl 1.349->1.010, Cd 0.0442->0.1458 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_mid2_nsga2_g04_child_0012_72b8e600 | mid2 | 0.0113842216 | 0.0113842216 | 1.25275937 | 0.115460181 | Re=300000, clean, alpha 14.50->16.50, Cl 0.781->1.093, Cd 0.0716->0.1959 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | True | True |
| cst_mid2_nsga2_g06_child_0034_4f56b056 | mid2 | 0.00955152333 | 0.00955152333 | 1.12017356 | -0.0171256302 | Re=320843, clean, alpha 15.50->16.50, Cl 0.606->0.993, Cd 0.1138->0.2172 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_mid2_seedless_sobol_0078_92a83118 | mid2 | 0.0150983351 | 0.0150983351 | 1.31923679 | 0.181937601 | Re=175000, clean, alpha 15.00->18.00, Cl 1.307->0.964, Cd 0.0851->0.2451 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_mid2_seedless_sobol_0619_a07c5c7e | mid2 | 0.0101166645 | 0.0101166645 | 1.29763968 | 0.160340493 | Re=400000, clean, alpha 14.00->17.50, Cl 0.835->1.100, Cd 0.0596->0.2267 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | True | True |
| cst_root_nsga2_g02_child_0112_57ba57cc | root | 0.0145345079 | 0.0149435502 | 1.63080761 | 0.263758138 | Re=175000, clean, alpha 8.00->10.00, Cl 1.230->0.923, Cd 0.0407->0.1251 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_root_nsga2_g03_child_0090_3408e0ca | root | 0.0108705077 | 0.011101079 | 1.60729077 | 0.240241304 | Re=100000, clean, alpha 17.50->18.00, Cl 1.623->1.262, Cd 0.1087->0.1946 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_XFOIL_branch_post_stall_issue | True | True |
| cst_root_nsga2_g07_child_0058_7b5c9763 | root | 0.0167407798 | 0.017224937 | 1.75900349 | 0.391954016 | Re=175000, clean, alpha 14.50->16.50, Cl 1.623->1.078, Cd 0.0630->0.2217 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_root_nsga2_g07_child_0109_fab67898 | root | 0.0158622567 | 0.016286926 | 1.62170218 | 0.254652714 | Re=150000, clean, alpha 15.00->16.00, Cl 1.696->1.185, Cd 0.0624->0.1696 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_root_nsga2_g07_child_0113_af0c4fa1 | root | 0.0147911272 | 0.0151821109 | 1.63170051 | 0.264651042 | Re=125000, clean, alpha 9.50->12.00, Cl 1.398->0.952, Cd 0.0550->0.1574 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_root_nsga2_g07_child_0119_2f486470 | root | 0.0147014183 | 0.0150995203 | 1.74408371 | 0.37703424 | Re=200000, clean, alpha 14.50->17.00, Cl 1.765->1.222, Cd 0.0443->0.1594 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | False | False |
| cst_tip_nsga2_g02_child_0085_cb99bc9c | tip | 0.010431642 | 0.011039501 | 1.23747958 | 0.342613319 | Re=125000, clean, alpha 12.50->14.50, Cl 0.765->0.968, Cd 0.0465->0.1845 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | True | True |
| cst_tip_nsga2_g04_child_0096_6230567a | tip | 0.0116385903 | 0.0123134342 | 1.40875724 | 0.513890984 | Re=258201, clean, alpha 15.00->16.00, Cl 1.274->0.999, Cd 0.1020->0.2077 | far_from_design_cl | low_far_from_design_cl | likely_sparse_alpha_grid_issue | True | True |
| cst_tip_nsga2_g05_child_0026_28eb9a70 | tip | 0.0119766838 | 0.012839884 | 1.18714196 | 0.292275704 | Re=300000, clean, alpha 15.00->17.50, Cl 0.704->1.012, Cd 0.0713->0.2156 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | True | True |
| cst_tip_nsga2_g06_child_0101_f4c46cf4 | tip | 0.0113148217 | 0.0119798137 | 1.21295979 | 0.31809353 | Re=345815, clean, alpha 11.50->15.00, Cl 0.813->1.033, Cd 0.0283->0.1624 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | True | True |
| cst_tip_seedless_sobol_0351_1048f012 | tip | 0.0135623316 | 0.0141085797 | 1.3169564 | 0.422090147 | Re=200000, clean, alpha 14.50->15.50, Cl 0.595->0.989, Cd 0.0945->0.1999 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_XFOIL_branch_post_stall_issue | False | False |

## Repair-Worthy Shortlist

| repair_rank | airfoil_id | zone | mean_cd | cd_p90 | stall_margin_cl | actual_cd_rank_in_zone | design_proximity | main_design_branch_risk | cause_category | trigger_region |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cst_mid2_seedless_sobol_0619_a07c5c7e | mid2 | 0.0101166645 | 0.0101166645 | 0.160340493 | 2 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=400000, clean, alpha 14.00->17.50, Cl 0.835->1.100, Cd 0.0596->0.2267 |
| 2 | cst_tip_nsga2_g02_child_0085_cb99bc9c | tip | 0.010431642 | 0.011039501 | 0.342613319 | 1 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=125000, clean, alpha 12.50->14.50, Cl 0.765->0.968, Cd 0.0465->0.1845 |
| 3 | cst_root_nsga2_g03_child_0090_3408e0ca | root | 0.0108705077 | 0.011101079 | 0.240241304 | 1 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_XFOIL_branch_post_stall_issue | Re=100000, clean, alpha 17.50->18.00, Cl 1.623->1.262, Cd 0.1087->0.1946 |
| 4 | cst_tip_nsga2_g06_child_0101_f4c46cf4 | tip | 0.0113148217 | 0.0119798137 | 0.31809353 | 2 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=345815, clean, alpha 11.50->15.00, Cl 0.813->1.033, Cd 0.0283->0.1624 |
| 5 | cst_mid2_nsga2_g04_child_0012_72b8e600 | mid2 | 0.0113842216 | 0.0113842216 | 0.115460181 | 3 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=300000, clean, alpha 14.50->16.50, Cl 0.781->1.093, Cd 0.0716->0.1959 |
| 6 | cst_tip_nsga2_g04_child_0096_6230567a | tip | 0.0116385903 | 0.0123134342 | 0.513890984 | 3 | far_from_design_cl | low_far_from_design_cl | likely_sparse_alpha_grid_issue | Re=258201, clean, alpha 15.00->16.00, Cl 1.274->0.999, Cd 0.1020->0.2077 |
| 7 | cst_tip_nsga2_g05_child_0026_28eb9a70 | tip | 0.0119766838 | 0.012839884 | 0.292275704 | 4 | near_design_cl_but_not_clear_main_branch | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=300000, clean, alpha 15.00->17.50, Cl 0.704->1.012, Cd 0.0713->0.2156 |

## Engineering Read

- Do not treat all CST `discontinuous_cd` failures as bad geometry. Several are otherwise competitive at the actual work points and fail on localized high-alpha branch behavior.
- Do not erase the archive warning either. The discontinuity threshold caught real polar-table behavior that can poison interpolation if the wrong branch is used.
- The next useful move is targeted polar repair for the shortlist, not broad NSGA reruns.
