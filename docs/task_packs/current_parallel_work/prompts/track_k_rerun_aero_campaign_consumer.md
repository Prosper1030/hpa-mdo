# Task Prompt: Track K Rerun-Aero Campaign Consumer

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**Wave 5 consumer 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `scripts/direct_dual_beam_inverse_design.py`

## 前提

這一包只有在 **Track J rerun-aero outer-loop core 已經 merge 並驗證** 之後才應開始。

## 任務目標

讓 campaign / winner selection 真正消費新的 rerun-aero artifacts，而不是繼續假裝所有 candidate 都只是 light refresh。

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- `scripts/dihedral_sweep_campaign.py`
- `tests/test_inverse_design.py`

## 完成條件

- campaign artifact 能辨識 rerun-aero vs legacy refresh
- winner / reject-reason / evidence 能反映新的 aero source
- 有最小必要測試，不要只改 report 欄位名稱

## 不要做

- 不要碰 `scripts/direct_dual_beam_inverse_design.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要碰 `src/hpa_mdo/utils/discrete_layup.py`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
