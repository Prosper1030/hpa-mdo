# Task Prompt: Track I Zone-Dependent Rules

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**第三波離散 layup 規則任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/dual_beam_recipe_library_architecture.md`

## 前提

這一包只有在 **spanwise DP discrete search 已經 merge 並驗證** 之後才應開始。

## 任務目標

把全翼一刀切的 thickness floor / ply-drop rule，改成更像工程現實的 zone-dependent rules。

## 推薦 write scope

- `src/hpa_mdo/utils/discrete_layup.py`
- `docs/dual_beam_preliminary_material_packages.md`
- `tests/test_discrete_layup.py`

## 完成條件

- 至少有 root / joint / clean outboard span 的區域規則差異
- 新規則不是單純放鬆限制，而是有對應 gate / 補強假設
- 測試能反映 zone-dependent 行為，而不是只有文件描述

## 不要做

- 不要碰 `src/hpa_mdo/structure/material_proxy_catalog.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
