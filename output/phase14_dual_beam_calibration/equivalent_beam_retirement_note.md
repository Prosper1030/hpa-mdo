# Why `equivalent_beam` Was Retained But Retired From Production Truth

## Short Answer

`equivalent_beam` was not abandoned because it was numerically wrong. It was retired from production truth because it became physically incomplete for the current design questions.

What its historical ANSYS parity proved was:

- the equivalent section properties were being computed consistently,
- the equivalent beam mass bookkeeping was consistent,
- the equivalent support mapping was consistent,
- and the equivalent-beam nodal load contract produced the same global response in ANSYS and the internal solver.

What it did not prove was:

- how front spar and rear spar split lift and self-weight,
- how the wire changes the real support path,
- how aerodynamic torque should be owned,
- how rib or link stiffness changes rear-spar motion,
- or whether rear-tip amplification is real, too large, or too small.

## What `equivalent_beam` Did Correctly

The equivalent-beam route reduced the front spar + rear spar section to one beam with one set of equivalent section properties.

That reduction is mathematically reasonable for some questions:

- `EI` tells you how hard it is to bend the section.
- `GJ` tells you how hard it is to twist the section.
- the parallel-axis theorem correctly increases bending stiffness when area is moved away from the neutral axis.

If the only question is:

- “For this one effective beam, do the internal solver and ANSYS predict the same deflection, reaction, and mass?”

then the equivalent-beam route is exactly the right benchmark.

That is why the Phase I parity pass matters. It proved the old route was internally self-consistent.

## What The Parity Pass Did Not Prove

An equivalent section can match global `EI` and `GJ` while still missing the real load path.

That matters here because the current wing is not just “one beam with the same stiffness.” It is:

- a front spar,
- a rear spar,
- a wire support,
- discrete main-to-rear load transfer through ribs or links,
- and aerodynamic torque that may act either as a torsional moment or as a front/rear vertical couple.

Two models can have similar total `EI` and still disagree on:

- which spar carries the load,
- where the maximum displacement occurs,
- how much the wire unloads the front spar,
- and how much the rear spar amplifies outboard motion.

That is exactly what the repo evidence shows. In the explicit two-beam checks, the active displacement moved to the rear outboard tip even though the equivalent-beam parity case had already passed.

## Why Parallel-Axis Equivalent `EI` Is Not Enough

The parallel-axis theorem is a section-property tool, not a load-path truth machine.

It answers:

- “If I collapse two separated tubes into one equivalent section, what total bending stiffness do I get?”

It does not answer:

- “How do the two tubes exchange load along the span?”
- “What happens if the connection between them is only at joints?”
- “How does the wire alter the reaction split?”
- “How should aerodynamic torque be applied to a two-spar system?”

Those are different questions.

For the current project, those different questions now matter more than the old single-beam parity question.

## Why The Current Design Needs `dual_beam_production`

The current repo mainline is:

`target loaded shape -> inverse design -> jig shape -> realizable loaded shape -> CFRP / discrete layup`

That workflow needs a structural model that can carry the right engineering ownership:

- front spar geometry and stiffness,
- rear spar geometry and stiffness,
- wire support behavior,
- torque and self-weight mapping,
- rib or link transfer between spars,
- and reactions that can be interpreted against the real current design.

`dual_beam_production` exists because the real design decisions now depend on those distinctions.

A single equivalent beam is still useful as a reference, but it is no longer enough as the production truth.

## Mechanics View Of The Missing Physics

### 1. Front / rear spar as a coupled section

An equivalent beam says “these two spars together are this stiff.”

The real current design also asks:

- how much load the front spar carries directly,
- how much the rear spar picks up through coupling,
- and whether that coupling is rigid, sparse, flexible, or wire-dominated.

### 2. Wire support reaction

In the old parity path, the wire is mostly a vertical support condition on one node.

In the production path, the wire is closer to a real cable or truss support:

- it has geometry,
- it can carry pretension,
- it should remain tension-only,
- and it can induce inboard precompression.

That affects both displacement and load sharing.

### 3. Torque as front/rear vertical couple

Aerodynamic pitching moment can be represented in more than one way:

- as a beam torsional moment `My`,
- or as a front/rear vertical force couple separated in `x`.

For a real two-spar model, those are not guaranteed to be equivalent once the wire, rigid links, and offset geometry are present.

The repo’s current Phase 13 diagnostics are already warning that torque ownership is one of the unresolved channels.

### 4. Rear-tip amplification

An equivalent beam naturally reports one beam-line tip response.

The explicit two-beam checks showed something more interesting:

- the outboard rear spar can move more than the main spar,
- and the active max `|UZ|` can sit on the rear tip.

That behavior is invisible in the old equivalent-beam sign-off path.

### 5. Rib / link stiffness

If front and rear spars are coupled only at a few joint stations, the rear spar can move differently from a model where every rib bay is very stiff.

That means the same total equivalent `EI` can still produce a different rear-tip response depending on link topology.

Again, the equivalent beam cannot resolve that.

## What `equivalent_beam` Is Still Good For

It still has value as:

- a regression check for equivalent section property math,
- a regression check for equivalent mass bookkeeping,
- a regression check for equivalent support reaction and deflection,
- a legacy gate reference while the dual-beam route is still being matured,
- and a way to detect when a new dual-beam or export change accidentally drifts the old baseline.

Those are real and useful jobs.

## What Should Not Be Promoted From `equivalent_beam`

These quantities should not be promoted from the equivalent-beam route into current production hard truth:

- front/rear spar load sharing,
- wire reaction partition,
- rear-tip amplification,
- rib or link stiffness adequacy,
- torque ownership decisions,
- current inverse-design sign-off,
- current dual-beam external calibration factors.

## Engineering Conclusion

The correct engineering summary is:

- `equivalent_beam` is numerically credible for the model it actually is.
- its ANSYS parity pass proved solver and export consistency for that model.
- it was retired from production truth because the project moved from a “global equivalent beam” question to a “real two-spar load-path and jig-shape” question.

So the right next step is not to throw away `equivalent_beam`. The right next step is to keep it as legacy parity evidence while calibrating `dual_beam_production` on a controlled external benchmark ladder.
