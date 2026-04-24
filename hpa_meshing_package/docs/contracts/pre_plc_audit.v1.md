# pre_plc_audit.v1

`pre_plc_audit.v1` moves 3D volume-entry risk discussion earlier in the pipeline.

## Purpose

Before `generate(3)` or later solver-entry claims, this audit should tell us:

- which risk families are already visible from topology-first descriptors
- which checks are implemented versus only reserved
- which artifact should be inspected before trying another single-case repair

## Required Checks

- `segment_facet_intersection_risk`
- `facet_facet_overlap_risk`
- `boundary_recovery_error_2_risk`
- `extrusion_self_contact_risk`
- `degenerated_prism_risk`
- `local_clearance_vs_first_layer_height`
- `manifold_loop_consistency`

## Each Check Carries

- `kind`
- `status`
- `assessment`
- `implemented`
- `summary`
- `entity_ids`
- `metrics`
- `notes`

## Current Minimal v1 Interpretation

- `local_clearance_vs_first_layer_height` is a real guard when both inputs exist
- `manifold_loop_consistency` is a real consistency check on the inferred IR loops
- observed topology failures and BL compatibility failures are tracked separately in the summary
- `observed_candidate` is available for runtime-native evidence that localizes a family but does not expose full contact geometry
- `extrusion_self_contact_risk` is treated as the BL-thickness / local-clearance compatibility line, not as proof of topology repair success
- `boundary_recovery_error_2_risk` is reserved for the downstream post-band transition family after the segment-facet string has already been displaced

### Failed-Steiner Boundary-Recovery Family

`boundary_recovery_error_2_risk` is now refined when Gmsh forensic evidence shows:

- `residual_family = boundary_recovery_error_2_recoversegment_failed_insert_steiner`
- `evidence_level = observed_candidate`
- `throw_site_label = addsteiner4recoversegment:failed_insert_steiner`
- `throw_site_file` / `throw_site_line`
- `local_surface_tags`
- `local_y_band`
- `suspicious_window`
- `sevent_e_type`
- `degenerated_prism_seen`

This is different from:

- the overlap family, which remains `facet_facet_overlap_risk`
- the generic segment-facet family, which remains `segment_facet_intersection_risk`
- generic `boundary_recovery_error_2_risk` without a throw-site payload

The throw-site evidence is stronger than a plain error string, so it is `observed_candidate`.
It is not full `observed` contact because the forensic rerun did not expose a `sevent` marker or
native `int_point` contact coordinate. If this payload is absent, the audit preserves the older
inferred / generic fallback instead of requiring this specific debug run.

## BL Clearance Compatibility Gate

`pre_plc_audit.v1` now carries a dedicated BL compatibility summary with:

- `total_bl_thickness_m`
- `min_local_clearance_m`
- `clearance_to_thickness_ratio`
- `verdict`

This gate is intentionally separate from observed topology failures such as:

- `segment_facet_intersection_risk`
- `facet_facet_overlap_risk`
- `boundary_recovery_error_2_risk`

## Planning Policy Promotion

When the BL clearance verdict is already `insufficient_clearance`, the artifact should also promote that into
a separate planning-policy block instead of leaving it as a late report-only observation.

The dedicated planning-policy fields are:

- `planning_policy`
- `planning_policy_fail_kinds`
- `planning_policy_recommendation_kinds`
- `planning_budgeting`

Current v1 meaning:

- `blocking_topology_check_kinds` tells you which topology-side families are still blocking
- `blocking_bl_compatibility_check_kinds` tells you the BL compatibility checks that failed
- `planning_policy_fail_kinds` tells you that the route should already be read as a BL-policy block, not as a topology-operator miss
- `planning_policy_recommendation_kinds` tells you which budgeting actions are currently recommended without changing runtime geometry
- `planning_budgeting` carries the sectionwise / regionwise tightness evidence behind those recommendations

The first explicit planning-policy fail kind is:

- `bl_clearance_incompatibility`

Current budgeting recommendation kinds are:

- `shrink_total_thickness`
- `split_region_budget`
- `stage_back_layers`
- `truncate_tip_zone`

## Sectionwise / Regionwise Budgeting

When sectionwise evidence is available, `pre_plc_audit.v1` now carries a separate budgeting payload with:

- `section_budgets`
- `region_budgets`
- `tightest_section_ids`
- `tightest_region_ids`
- `tightest_sections`
- `tightest_regions`
- `recommendation_kinds`

Each section / region entry can now also surface:

- explicit `span_y_range_m`
- ratio deficits such as `clearance_to_thickness_ratio_deficit` and `available_budget_ratio_deficit`
- `clearance_pressure`
- per-kind `recommendations` with direction and, when applicable, delta fields such as `delta_total_thickness_m`, `delta_total_thickness_ratio`, or `suggested_truncation_start_y_m`
- plan-only `manual_edit_candidates` for tight windows and regions

This budgeting line is intentionally separate from topology-family progress:

- it explains where the BL budget is tight
- it suggests how planning could respond
- it does **not** silently mutate geometry, BL layers, or shell_v4 runtime defaults

That means a report can now say both:

- topology still blocks on one observed family
- BL budgeting also recommends `split_region_budget` or `truncate_tip_zone`

and the tightest-section summary can still tell you:

- which span window is actually pressured
- how far the budget ratio is below 1.0
- whether the first actionable move is shrinking thickness, splitting the budget zone, staging back layers, or moving truncation inboard

without mixing those two judgments together.

## Topology + BL Handoff Summary

When shell_v4 runs the topology compiler in `plan_only`, the route can also write
`topology_bl_handoff_summary.v1.json`.

This artifact is a compact decision view over the topology compiler summary, operator regression
artifact, and BL budgeting report. For each focused family it surfaces:

- current verdict, including `topology_attempted_but_bl_policy_blocked`
- `residual_family`
- `evidence_level`
- `throw_site_label`
- `local_y_band`
- `suspicious_window`
- `degenerated_prism_seen`
- `operator_action_kind`
- `operator_result_status`
- `topology_recommended_next_action`
- BL blocking / policy fail kinds
- BL recommendation kinds
- top 1-3 plan-only manual edit candidates
- BL stageback / truncation candidate comparison
- `recommended_candidate_id`
- recommendation reason
- whether a focused topology rerun is recommended after candidate application
- whether runtime apply remains disabled
- final handoff verdict such as `local_transition_regularization_candidate`,
  `requires_tip_zone_bl_stageback`, `topology_attempted_but_bl_policy_blocked`,
  `runtime_rerun_required`, or `unresolved_same_failed_steiner_family`

It is intentionally plan/report-only. It must not change runtime geometry, BL settings, or route
success/failure semantics.

## BL Stageback / Truncation Candidate Comparison

When failed-Steiner evidence remains after the bounded topology operator and the BL policy is already
blocking, `plan_only` can also write:

- `bl_stageback_truncation_candidate_comparison.v1.json`

This artifact compares BL-policy candidates instead of adding another topology operator. The current
candidate kinds are:

- `baseline`
- `tip_zone_stageback`
- `tip_zone_truncation`
- `split_region_budget`
- `shrink_total_thickness`
- `stageback_plus_truncation`

Each candidate carries:

- `candidate_id`
- `candidate_kind`
- `target_y_span`
- `target_surface_or_region_hint`
- `original_total_bl_thickness`
- `proposed_total_bl_thickness` and/or `proposed_layer_count`
- `estimated_clearance_ratio_after`
- `estimated_ratio_deficit_after`
- `expected_effect_on_failed_steiner`
- `expected_effect_on_degenerated_prism`
- `risk_notes`
- `planning_only = true`

The comparison is derived from budgeting evidence only. It does not mean the BL spec has been changed,
does not mutate production defaults, and does not activate a runtime apply path. If a later round wants
to test one candidate, it must introduce a separate explicit experimental apply gate and then rerun the
focused topology validation.

## Experimental Focused Apply Gate

The explicit focused apply gate is separate from `topology_compiler_gate`:

- Python argument: `bl_candidate_apply_gate`
- default: `off`
- enabled value: `stageback_plus_truncation_focused`
- CLI flag: `--apply-bl-stageback-plus-truncation-focused`

When enabled, only `bl_candidate_stageback_plus_truncation` may be applied, and only inside an isolated
root_last3 focused validation rerun. The gate writes:

- `applied_candidate.v1.json`
- `bl_candidate_apply_comparison.v1.json`

`plan_only` remains artifact-only, `topology_compiler_gate=off` remains a no-op, and production
defaults are not changed. The success criteria are not a full prelaunch pass. The comparison only asks
whether failed-Steiner residual evidence, degenerated-prism evidence, local y band, suspicious window,
or downstream failure family improves or shifts.

The current `stageback_plus_truncation_focused` result is classified as too aggressive: it removed the
failed-Steiner residual family but reintroduced `segment_facet_intersection`, while degenerated-prism
evidence remained present. This is a regression to an upstream PLC / segment-facet family, not a
production-ready improvement.

## Experimental Focused Parameter Sweep

The focused sweep is a report-only follow-up to the too-aggressive apply result:

- CLI flag: `--run-bl-candidate-sweep-focused`
- artifact: `bl_candidate_parameter_sweep.v1.json`
- focused path: `root_last3_segment_facet`
- full prelaunch pass attempted: `false`

Each sweep case must report before/after failure kind, residual family, failed-Steiner resolution,
segment-facet regression, degenerated-prism evidence, local y band, suspicious window, and a verdict.
The allowed production interpretation is deliberately conservative:

- `too_aggressive_reintroduces_segment_facet` means the case is rejected for runtime apply.
- `insufficient_still_failed_steiner` means the BL intervention did not move the blocker far enough.
- `promising` only means failed-Steiner disappeared without returning to segment-facet; it is still
  experimental evidence, not a default route change.
- `stageback_induced_1d_loop_closure_failure` means a stageback-only case moved away from the
  failed-Steiner residual but collapsed earlier: the surface meshing boundary no longer formed a
  closed 1D loop, zero BL layers were achieved, and the case did not reach Gmsh 3D boundary
  recovery. This is not promising evidence; it is a separate topology/collapse diagnostic family.

The sweep exists to find the minimum safe intervention. It must not mutate `shell_v4` defaults, must
not change `topology_compiler_gate=off`, must not make `plan_only` apply geometry, and must not add a
topology operator. A future experimental apply should only be considered after a `promising` sweep case
exists.

## Manual Edit Candidates

`manual_edit_candidates` are a human-facing planning view derived from the same budgeting evidence.

Each candidate carries:

- target section or region id
- `span_y_range_m`
- current total BL thickness
- min local clearance inferred from section half-thickness sampling
- current clearance ratio and ratio deficit
- suggested max total BL thickness
- suggested thickness reduction
- suggested truncation start y
- suggested split boundary y
- suggested layer stage-back direction
- `planning_only = true`

These candidates are not runtime mutations. They should be read as "what a human should inspect next,"
not as an instruction to automatically change shell geometry, BL layer count, total thickness, or
route verdict.

## Important Limitation

`pre_plc_audit.v1` is not a full PLC solver or reproducer.

It is an honest front-loaded audit artifact so later work can target the right family with better evidence.
