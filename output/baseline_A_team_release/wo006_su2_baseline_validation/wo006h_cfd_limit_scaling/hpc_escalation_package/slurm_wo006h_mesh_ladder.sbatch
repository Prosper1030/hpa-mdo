#!/usr/bin/env bash
#SBATCH --job-name=wo006h-cfd
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=wo006h-%j.log

set -euo pipefail
module purge || true
module load python || true
module load gmsh || true
module load su2 || true

export REPO_ROOT="${REPO_ROOT:-$PWD}"
export OUT_DIR="${OUT_DIR:-$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_hpc_run}"
export MESH_TIMEOUT_SECONDS="${MESH_TIMEOUT_SECONDS:-7200}"
export CORE_TIMEOUT_SECONDS="${CORE_TIMEOUT_SECONDS:-1800}"
bash "$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_cfd_limit_scaling/hpc_escalation_package/run_hpc_campaign.sh"
