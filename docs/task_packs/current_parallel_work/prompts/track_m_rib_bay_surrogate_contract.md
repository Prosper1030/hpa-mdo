# Task Prompt: Track M Rib Bay Surrogate Contract

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**rib passive-surrogate 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `scripts/direct_dual_beam_inverse_design.py`

## 前提

這一包只有在 **Track L rib properties foundation 已經 merge / verify** 之後才應開始。

## 任務目標

先把 rib 對 bay / shape-retention 的影響，變成 candidate summary 可消費的 surrogate contract。

這一包是 report / soft-gate 層，不是 full rib optimization。

## 這包最低要做到的事

- 有一個 rib bay surrogate helper
- candidate artifact / summary 能輸出至少一組像下面這樣的資訊：
  - bay length
  - local `Δ/c`
  - shape-retention risk 或等價指標
- 測試能驗證這些欄位不是空字串，而是真的由 contract 推出

## 推薦 write scope

- `src/hpa_mdo/structure/rib_surrogate.py`
- `scripts/direct_dual_beam_inverse_design.py`
- `tests/test_inverse_design.py`

## 完成條件

- candidate summary 可見 rib bay surrogate
- 這些指標還不必第一天就當 hard constraint，但不能只是文件敘述
- 有最小必要測試

## 不要做

- 不要碰 `src/hpa_mdo/structure/dual_beam_mainline/**`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要自行擴張成 zone-wise rib optimization
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
