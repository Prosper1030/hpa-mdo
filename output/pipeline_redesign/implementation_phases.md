# Implementation Phases

## Phase 0: Freeze Definitions

Goal: prevent another confusing comparison where mass changes because the structural state changed silently.

Tasks:

- Define `StructuralBudgetContract` in a config or JSON schema.
- Define `FourierTargetContract`, `AVLRealizationContract`, and `ZStateSearchContract`.
- Require every result row to include actual target main/rear tip Z, not only a multiplier.
- Require mass fields to say whether they are tube-only or total structural mass.

Success criteria:

- A candidate report can answer: spanload target, AVL actual spanload, target Z state, jig result, and tube mass from one row.

## Phase 1: MVP Z-State Structural Prefilter

This is the first MVP implementation step.

Build a wrapper, tentatively:

```text
scripts/structure_budgeted_z_state_search.py
```

Inputs:

- one section table from the upstream/Fourier-AVL geometry
- one AVL file and spanwise load artifact
- `StructuralBudgetContract`
- target main-tip Z sweep range
- canonical inverse-design config template

Processing:

- generate requested loaded-Z states
- call `scripts/direct_dual_beam_inverse_design.py`
- use `candidate_avl_spanwise` for AVL spanwise lift ownership
- keep `refresh_steps=0` for MVP comparability
- collect tube mass, clearance, prebend, wire, moment-closure fields when available

Outputs:

- `z_state_structure_budget_sweep.csv`
- `z_state_structure_budget_summary.md`
- `feasible_loaded_shape_shortlist.csv`

MVP pass condition:

- At least one candidate row clearly says whether it can pass `spar_tube_mass_target_kg = 11.5` or the diagnostic `11.7534 kg` line.
- The output reports practical clearance bands, not only a mathematical mass pass.

## Phase 2: Fourier-AVL Alignment Module

Build a reusable comparator:

```text
src/hpa_mdo/concept/fourier_avl_alignment.py
```

Inputs:

- Fourier target loading on a station grid
- AVL spanwise load output
- geometry station table

Outputs:

- `target_vs_avl_rms`
- `target_vs_avl_outer_delta`
- `target_vs_avl_max_delta`
- `outer_underloaded`
- `inner_overloaded`
- `alignment_status`
- `diagnosis`

Decision logic:

- If AVL sanity fails, return `avl_contract_invalid`.
- If mismatch is high and local Cl limits are active, return `target_not_realizable_with_current_geometry`.
- If mismatch is low but e_CDi is poor, return `target_low_value`.
- If mismatch and e_CDi pass, return `spanload_realized`.

## Phase 3: Upstream Candidate Loop Reorder

Modify the upstream concept pipeline order:

```text
Fourier target
-> smooth geometry realization
-> AVL realization
-> Fourier-AVL alignment
-> structural Z-state budget search
-> feasible loaded-shape shortlist
-> AVL loaded-shape recheck
-> Tier2 DB zone airfoil search
```

Important change:

- Tier2 airfoil selection moves after structural loaded-shape feasibility.
- Structure budget is no longer a final audit; it becomes a pre-airfoil gate/score.

## Phase 4: Tier2 Full-Alpha Integration

Reuse the smooth-geometry combo reoptimization pattern, but feed it feasible loaded-shape AVL actual Cl/Re.

Tasks:

- Build zone envelopes from AVL loaded-shape recheck.
- Query Tier2 full-alpha DB.
- Build root/mid1/mid2/tip pools.
- Run capped AVL reruns for combinations.
- Integrate profile drag from actual Cl/Re.

Outputs:

- `tier2_zone_envelopes.csv`
- `tier2_candidate_pools.csv`
- `tier2_combo_results.csv`
- `best_aero_candidate.md`
- `best_structure_feasible_candidate.md`

## Phase 5: Dual-Leaderboard Reporting

Add final reporting:

```text
output/upstream_pipeline_runs/<run_id>/
  fourier_targets.csv
  avl_realization_comparison.csv
  z_state_structure_budget_sweep.csv
  feasible_loaded_shape_shortlist.csv
  tier2_combo_results.csv
  aero_best_candidate.md
  structure_feasible_production_candidate.md
```

The report must never hide disagreement:

- If aero best fails mass budget, show the Z state needed to recover it.
- If production best has higher power, show the power penalty.
- If Fourier and AVL disagree, show whether AVL contract or target realizability is the driver.

## Phase 6: Optional Finalist Confirmation

Only after a production candidate exists:

- candidate-owned VSPAero rerun
- refined inverse-design refresh
- discrete CFRP/layup realization
- high-fidelity structural spot-check if needed
- SU2/XFOIL verification of selected airfoil work points

This is not part of the MVP because the first missing layer is structure-budgeted loaded-shape search before airfoil optimization.

## First MVP Step

Implement `scripts/structure_budgeted_z_state_search.py` by generalizing the proven smooth baseline z-state sweep. It should consume a candidate section table and AVL spanwise artifact, run canonical inverse design across a requested loaded-Z band, and emit a clean structural budget table before Tier2 airfoil selection.

That one step directly answers the current process gap: "what loaded Z state makes this geometry fit the 11.5 kg class before we spend time optimizing airfoils?"
