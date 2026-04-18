# Task Prompt: Track O Zone-Wise Rib Design Contract

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**rib optimizer-integration 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `scripts/direct_dual_beam_inverse_design.py`

## 前提

這一包只有在 **Track M rib bay surrogate** 和 **Track N passive rib robustness mode** 都已經 merge / verify 之後才應開始。

## 任務目標

把 rib 正式納入結構主線，但只用**有限度的 zone-wise 設計自由度**。

不是每根 rib 一個變數，而是：

- mandatory ribs 固定
- 少量 zone-wise rib pitch 選項
- 少量 zone-wise rib family 選項

## 這包最低要做到的事

- 結構主線能表達 zone-wise rib pitch / family
- winner selection / candidate summary 能消費 rib design 結果
- mix mode 若存在，至少有切換懲罰或材料數量上限

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design.py`
- `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- `tests/test_inverse_design.py`

## 完成條件

- rib 不再只是 report-only，而是有限度進入 candidate design contract
- 沒有退化成 per-rib combinatorial explosion
- 有最小必要測試

## 不要做

- 不要碰 `src/hpa_mdo/hifi/**`
- 不要做 rib cutout / topology optimization
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
