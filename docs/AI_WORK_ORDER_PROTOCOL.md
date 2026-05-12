# AI Work Order Protocol

This protocol turns Baseline A from a single-person deep-development flow into a
team release plus AI work-order queue. It applies to Codex threads working in
`/Volumes/Samsung SSD/hpa-mdo`.

## Current Blocking Gate

Baseline A is under data-authority repair. Before any worker starts WO-006 SU2,
WO-007 QPROP/XROTOR, RFQ procurement, vendor selection, or release claims, run:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/check_baseline_a_data_authority.py --check-only
```

Current authority:

- `98.5 kg` is design gross mass authority.
- `106.828608 kg` is suspect P1 screening aggregate only.
- `34.332286 m` / `17.166143 m` are current pipeline span evidence.
- `16.5 m` is local/splice screening only, not procurement truth.
- WO-005 is draft/vendor-screening only.
- WO-006 stays paused until data authority is restored.

## Baseline A Rule

Baseline A is a data-authority repair package, not final aircraft sign-off.

The current generated evidence package is:

- `output/baseline_A_team_release/baseline_A_team_release.md`
- `output/baseline_A_team_release/geometry_freeze.json`
- `output/baseline_A_team_release/mass_budget.csv`
- `output/baseline_A_team_release/cg_summary.json`
- `output/baseline_A_team_release/margin_budget.md`
- `output/baseline_A_team_release/manufacturable_geometry_audit/`
- `output/baseline_A_team_release/carbon_tube_rfq_pack.md`
- `output/baseline_A_team_release/controlled_station_span_splice_manifest.csv`
- `output/baseline_A_team_release/procurement_risk_register.json`
- `output/baseline_A_team_release/team_work_packages.md`

The current structural blocker verdict is
`p1_local_load_path_ready_for_coupon_fem`. That means P1 can proceed to
coupon/local FEM. It does not prove final adhesive, laminate, tube-wall,
buckling, manufacturing, flight-dynamics, or aircraft sign-off.

The current mass / CG / margin ledger verdict is
`mass_cg_margin_ledger_ready`. Its rows are screening estimates unless a row
explicitly says otherwise; managed CG is the `0.75 m` screening row and
uncompensated CG remains rejected.

The current manufacturable geometry audit verdict is
`geometry_freeze_needs_fix`. The smooth pathfinder is usable for Baseline A
team-release engineering work, but continuous dimensions, station/span/splice
contracts, and RFQ/shop-facing tube/rib/control stations are not final drawing
control. WO-005 carries those warnings into vendor-screening language instead
of treating them as either final sign-off or immediate Baseline A reopen.

The current carbon tube RFQ pack is `carbon_tube_rfq_pack_draft_vendor_screening`.
It may support internal vendor-question drafting only. It does not authorize tube
purchase, supplier selection, shop drawings, spar-spec changes, procurement
truth, or final aircraft sign-off. Vendor evidence that invalidates tube OD/wall,
splice fit, layup/modulus, mass/CG, 3 m shipping, or y=3 m inboard splice
assumptions must return through change control after mass/span authority is fixed.

## Worker Startup

Every AI worker must first read:

1. `README.md`
2. `CURRENT_MAINLINE.md`
3. `docs/AI_WORK_ORDER_PROTOCOL.md`
4. `docs/work_orders/QUEUE.md`
5. The specific work-order prompt
6. `output/baseline_A_team_release/` when the task touches Baseline A

If these sources conflict, use this priority:

1. Latest explicit user instruction
2. `CURRENT_MAINLINE.md`
3. `output/baseline_A_team_release/data_authority_table.csv`
4. `docs/reports/baseline_A_data_authority_conflict_register.md`
5. `README.md`
6. Generated outputs such as `geometry_freeze.json`
7. Older reports and task packs

## Work Order Lifecycle

1. Pick the highest-priority unblocked work order.
2. State whether the task is code, docs, analysis, or generated artifact work.
3. Keep the write scope narrow.
4. Run the smallest credible verification first, then broader verification if
   the change affects shared behavior.
5. Update `README.md` and/or `CURRENT_MAINLINE.md` when the task changes the
   formal pipeline, recommended commands, candidate state, engineering trust
   boundary, next priority, or public claim language.
6. Output a reviewer prompt that another Codex thread can use to audit the work.
7. Run `git add -p` for only relevant files and commit one work order per commit.

## Mandatory Review Labels

Every work-order report must choose one of these labels:

- `pass`: evidence supports the work-order claim inside the stated trust boundary.
- `needs_fix`: useful progress, but an implementation or documentation issue
  remains before the work order can close.
- `dangerous_assumption`: the result is likely to mislead future work unless the
  assumption is corrected or quarantined.
- `reopen_risk`: the finding may force Baseline A redesign or user decision.

## Decision Escalation

Ask the user only when the work affects one of these:

- Large external shape or main planform
- Main/rear spar specification
- Weight/CG or rebalance strategy
- Procurement commitment
- Baseline A reopen trigger

Do not ask for routine local choices such as report wording, test slice choice,
or internal helper structure.

## Engineering Honesty Checklist

Before reporting success, check:

- Are units and sign conventions explicit?
- Is load ownership clear?
- Is the result screening, coupon/FEM, or final evidence?
- Did the task accidentally treat QPROP/XROTOR as structural-blocker truth?
- Did it turn the direct spar-pair stress-test warning into aero-surface sign-off?
- Did it hide the C04 original peel fail evidence?
- Did it accept uncompensated CG?
- Did it overclaim from passing tests?

## Verification Minimum

Each worker should run:

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest <relevant tests>
PYTHONPATH=src ./.venv/bin/python -m ruff check <changed python files or dirs>
git diff --check
```

If the task changes generated release artifacts, also rerun:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/build_baseline_a_release.py
```

## Required Report Shape

Each worker final report must include:

- verdict
- changed files
- verification
- engineering caveats
- reviewer prompt
- next recommended work order

Keep the report short enough for a 30-minute daily review.
