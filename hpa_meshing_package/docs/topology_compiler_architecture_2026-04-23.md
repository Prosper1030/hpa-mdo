# Topology Compiler v1 Architecture Note (2026-04-23)

## Why this round moves from single-case repair to topology compiler

The current blocker is no longer the older closure-ring / single-face patch problem by itself.

The real-wing BL line has already pushed the main uncertainty further downstream:

- 3D volume-side consistency
- solver-entry family behavior
- PLC / degenerated-prism style risk that is larger than one broken patch

At that point, continuing to hard-patch one case at a time becomes misleading.

What we need first is a family-level compiler skeleton:

- a topology-first IR
- a named motif registry
- an explicit operator library
- a pre-PLC audit artifact

That gives later work a clean place to land without pretending this round already repaired every real-wing prelaunch failure.

## Role split: shell_v3, shell_v4, esp_rebuilt, compiler layer

### `esp_rebuilt`

`esp_rebuilt` remains the normalized-geometry producer.

It already emits the artifacts this v1 compiler consumes:

- `topology.json`
- `topology_lineage_report.json`
- `topology_suppression_report.json`

The compiler layer sits **after** those artifacts, not inside the provider runtime.

### `shell_v3`

`shell_v3` stays frozen.

Its job is still:

- frozen geometry baseline
- coarse CFD baseline
- regression reference

It is explicitly **not** reopened as the BL mainline and this compiler layer does not give it permission to mutate that role.

### `shell_v4`

`shell_v4` remains the active BL / solver-validation branch.

Its job is:

- real-wing BL topology exploration
- solver-entry contract exploration
- future consumption of topology-family artifacts

It does **not** become the new geometry baseline just because it is the active validation branch.

### `topology compiler v1`

The new compiler layer is a separate planning/analysis stratum between provider artifacts and family-level operator work.

Its current outputs are:

- `topology_ir.v1`
- `motif_registry.v1`
- `operator_plan.v1`
- `pre_plc_audit.v1`
- `topology_compiler.v1`

This keeps the architecture honest:

- `esp_rebuilt` materializes geometry
- compiler classifies topology families
- `shell_v4` later consumes those families for BL / solver-entry work
- `shell_v3` remains the frozen regression truth

## What is complete in this round

- versioned compiler package under `src/hpa_meshing/compiler/`
- `topology_ir.v1` models plus builder from existing `esp_rebuilt` artifacts
- `motif_registry.v1` with the requested first-wave motif kinds
- `operator_library.v1` with the first real `TRUNCATION_CONNECTOR_BAND -> regularization` operator
- `pre_plc_audit.v1` schema plus explicit BL-clearance-compatibility reporting that stays separate from topology failures
- `topology_compiler.v1` artifact writer and shell-role policy split
- tests for schema, registry wiring, deterministic reject, and shell role separation

## `TRUNCATION_CONNECTOR_BAND` v1 operator scope

The first implemented operator is intentionally local:

- it only regularizes the terminal truncation connector band
- it canonicalizes one extra pre-band support strip into the 4-anchor family
- it is meant to consume the observed overlapping-facet family before we claim any whole-wing rewrite

What it does **not** mean:

- not a whole-wing topology rewrite
- not a root-closure redesign
- not proof that segment-facet or BL-thickness failures are solved everywhere

The current honest outcome is:

- `root_last4_overlap` can be regularized away from the original overlap family
- `root_last3_segment_facet` remains a real observed family after canonicalization, but it is now treated as a distinct post-band transition family instead of "reject + unchanged"
- BL thickness / local clearance compatibility is now a separate planning-policy block, not just an audit note

## Second observed family: canonical connector-band post-transition

The newer observed family is intentionally **not** another overlap rewrite.

After `regularize_truncation_connector_band` consumes the extra pre-band support strip, the remaining
`root_last3_segment_facet` fixture is already the canonical three-strip chain:

- `root_to_terminal_support`
- `connector_band`
- `truncation_transition`

That means the old overlap family has already been separated out.

The remaining observed blocker is now interpreted as a post-band transition family:

- zero `pre_band_support` strips remain
- the connector band itself is already canonical
- the unresolved observed blocker is still `segment-facet intersection`
- a prototype split inside the post-band transition interval can move the downstream failure away from the original segment-facet string, which is useful regression evidence even though it is not a full fix yet

This round therefore adds an explicit prototype operator for the canonical post-band transition family
instead of pretending the first overlap operator just needs to be widened.

## Third observed family: post-band transition boundary recovery `error 2`

The next family downstream is deliberately no longer described as a segment-facet problem.

Once the canonical post-band transition prototype inserts one deterministic guard section, the
reproducer can leave the original `segment-facet intersection` string entirely and fail later with:

- `Could not recover boundary mesh: error 2`

That change is not treated as "mission accomplished." It is treated as evidence that the unresolved
family has moved into a different stage with a different locus:

- the connector band is still canonical
- overlap-family evidence is already consumed
- the split post-band transition interval is now the geometry-contact locus
- the observed blocker is better named as a boundary-recovery family, not a renamed overlap case

This round therefore promotes the new line explicitly:

- new observed topology check: `boundary_recovery_error_2_risk`
- new motif family: `POST_BAND_TRANSITION_BOUNDARY_RECOVERY`
- new bounded prototype operator: `prototype_regularize_post_transition_boundary_recovery`

What this does mean:

- the `error 2` family is now classified and regression-tested as its own post-band transition line
- applicability and reject semantics are deterministic
- artifacts now carry a bounded guard-to-tip relief mutation with before/after interval evidence instead of only quoting a downstream string
- the current prototype intentionally snaps the relief section to a coarse rounded spanwise location so the mutation stays reproducible and readable

What this still does **not** mean:

- not a production repair for boundary recovery
- not proof of full prelaunch success
- not evidence that real-wing or whole-case PLC routing is globally solved

## BL compatibility as planning policy, not topology blame

The BL clearance ratio line is now promoted one level higher in the artifacts.

When `clearance_to_thickness_ratio` is already badly out of balance, the compiler should report:

- topology blockers
- BL compatibility blockers
- planning-policy fail kinds
- planning-policy recommendation kinds

separately.

That separation matters because a failing BL policy verdict should tell later users:

- do not misread this as "the topology operator simply needs one more tweak"
- do not merge the BL incompatibility line into the canonical post-band transition family
- do treat it as an independent route-level incompatibility that can block planning even while topology-family work is still progressing

This round also pushes the BL line beyond a single block/fail verdict.

When shell_v4 can provide spanwise sampling evidence, the compiler now carries:

- sectionwise budgeting pressure
- regionwise budgeting pressure
- tightest sections / tightest regions
- plan-only recommendation kinds such as shrinking thickness, splitting the budgeted zone, staging back layers, or truncating the tip zone

That advice is still intentionally bounded:

- it is planning guidance, not runtime geometry mutation
- it does not auto-apply an operator
- it must stay readable as a separate BL-policy line alongside topology-family progress

## What is intentionally still skeleton / TODO

- no native BREP-edge extraction yet; `topology_ir.v1` currently uses artifact-inferred section strips
- no claim that the connector-band operator is fully generalized beyond the one-extra-support-strip family
- no claim that the new post-band transition prototypes are the final production operators
- no automatic integration into the live `shell_v4` runtime path yet

Those are intentional boundaries, not missing polish.

The point of v1 is to expose the landing zones before another round of family-level implementation.

## Recommended next step after this round

1. Add a reproducible PLC-family fixture set and promote the current placeholder checks into real geometric audits.
2. Connect one real `shell_v4` family path to `topology_compiler.v1` under a clear feature gate, still plan-only by default.
3. Implement the first non-reject operator on a bounded family, most likely the truncation connector band or closure-ring fill path with dedicated artifacts.
