# Fine TE-Fixed yPlus Report

Verdict: `no qualified Fine yPlus`

The Fine TE-fixed solver did not complete a stable run. The available
`postProcessing/yPlus/0/yPlus.dat` file contains only the header:

```text
# y+ ()
# Time        patch        min        max        average
```

Because the Fine run stopped at pseudo-time 1 under the force-runaway guard,
there is no qualified Fine y+ distribution to compare against Medium/reference.

For context only, the accepted reference route-smoke had real airfoil-wall y+
inside the intended low-y+ range:

| reference route | y+ mean | y+ p95 | y+ max |
|---|---:|---:|---:|
| accepted route-smoke primary airfoil walls | `0.5678595` | `1.0904245` | `2.65697` |

That reference y+ does not qualify the Fine mesh; it only shows the prior
Medium/reference route-smoke was near-wall resolved on the airfoil walls.
