# WO-006H HPC Escalation Package

This package is for current Baseline A main-wing CFD route escalation. It does
not change external geometry or authority values.

Run from a machine with this repo, Gmsh, SU2, and Python dependencies:

```bash
export REPO_ROOT=/path/to/hpa-mdo
bash "$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_cfd_limit_scaling/hpc_escalation_package/run_hpc_campaign.sh"
```

For Slurm:

```bash
cd "$REPO_ROOT"
sbatch output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_cfd_limit_scaling/hpc_escalation_package/slurm_wo006h_mesh_ladder.sbatch
```

Acceptance is not "SU2 ran." A result is usable only after authority, marker,
BL/y+, mesh quality, force stability, convergence, and mesh-sensitivity gates
pass. No-BL mesh rungs are resource/sign/marker controls, not HPA drag truth.
