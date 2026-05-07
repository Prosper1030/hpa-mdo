# Smooth Geometry Combo Re-optimization Summary

Generated: 2026-05-07T04:53:58.514734Z

## Direct Answers

- Smoothing penalty without airfoil reselection: 13.497 W crank.
- Recovered by smooth-geometry Tier2 reselection: 9.777 W crank.
- Remaining penalty versus original faceted raw best: 3.720 W crank.
- Recovered by archive+actual-pass production-quality reselection: 9.327 W crank.
- Remaining archive+actual-pass penalty versus original faceted raw best: 4.170 W crank.
- Best smooth-monotone performance assignment: `root:dae21|mid1:dae21|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136` at 170.710 W crank.
- Best smooth-monotone production-quality assignment: `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g06_child_0056_b3f9b7c4` at 171.160 W crank.
- Smooth reoptimized beats old FX/Clark: True.
- Beats previous Policy A smooth: True.
- Beats previous Policy C smooth: True.
- Production-facing aero baseline: new archive+actual-pass smooth combo wins; keep structural/jig caveats from Phase 9.

## Engineering Read

This is still a sidecar aerodynamic re-optimization. It updates airfoil assignments for the smooth production geometry, but does not change production ranking, hard gates, Fourier settings, or structural feasibility status. The absolute performance winner is useful evidence; the archive+actual-pass winner is the safer production-facing aero recommendation.
