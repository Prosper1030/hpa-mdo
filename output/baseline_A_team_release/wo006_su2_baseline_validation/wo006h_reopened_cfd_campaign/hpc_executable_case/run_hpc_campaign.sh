#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/Volumes/Samsung SSD/hpa-mdo}"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006h_hpc_run}"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${SU2_BIN:-/Users/linyuan/.local/opt/su2/current/bin}:$PATH"
export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/hpa_meshing_package/src:${PYTHONPATH:-}"

cd "$REPO_ROOT"
"$PYTHON" scripts/check_baseline_a_data_authority.py --check-only

run_case() {
  local case_name="$1"
  shift
  "$PYTHON" scripts/run_wo006h_cfd_limit_scaling.py \
    --output-dir "$OUT_DIR/$case_name" \
    "$@" \
    --mesh-timeout-seconds "${MESH_TIMEOUT_SECONDS:-7200}" \
    --core-timeout-seconds "${CORE_TIMEOUT_SECONDS:-7200}" \
    --clean
}

run_case mesh_h0055_hxt --mesh-sizes 0.055 --skip-core-variants
run_case mesh_h005_hxt --mesh-sizes 0.05 --skip-core-variants
run_case mesh_h004_hxt --mesh-sizes 0.04 --skip-core-variants
run_case mesh_h004_delaunay --mesh-sizes 0.04 --no-bl-mesh-algorithm3d 1 --skip-core-variants
run_case bl_core_variants_32x2 --skip-no-bl-ladder

"$PYTHON" scripts/run_wo006h_reopened_cfd_campaign.py \
  --input-dir "$OUT_DIR" \
  --output-dir "$OUT_DIR/final_report" \
  --hpc-package-dir "$PACKAGE_DIR"
