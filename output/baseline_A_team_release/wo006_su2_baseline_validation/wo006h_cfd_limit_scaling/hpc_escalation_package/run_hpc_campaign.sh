#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/Volumes/Samsung SSD/hpa-mdo}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_hpc_run}"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
export PATH="${SU2_BIN:-/Users/linyuan/.local/opt/su2/current/bin}:$PATH"
export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/hpa_meshing_package/src:${PYTHONPATH:-}"

cd "$REPO_ROOT"
"$PYTHON" scripts/check_baseline_a_data_authority.py --check-only
"$PYTHON" scripts/run_wo006h_cfd_limit_scaling.py \
  --output-dir "$OUT_DIR" \
  --mesh-sizes 0.12 0.10 0.08 0.06 \
  --mesh-timeout-seconds "${MESH_TIMEOUT_SECONDS:-7200}" \
  --core-timeout-seconds "${CORE_TIMEOUT_SECONDS:-1800}" \
  --clean
