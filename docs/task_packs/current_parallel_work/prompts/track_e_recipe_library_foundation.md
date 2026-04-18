# Task Prompt: Track E Recipe Library Foundation

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**主線設計空間修正任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/dual_beam_recipe_library_architecture.md`
5. `docs/dual_beam_preliminary_material_packages.md`

## 任務目標

把 discrete layup 的材料空間，從偏 fixed-family round-up 的 catalog，升成 **功能型 recipe library foundation**。

這一包的目標是打地基，不是一次把整個 selector 和 spanwise search 都做完。

## 這包要完成什麼

- 讓 catalog 能清楚表達：
  - bending-dominant recipes
  - balanced torsion recipes
  - joint / hoop-rich local recipes
- 建立清楚的 property-row / lookup contract
- 保持 backward compatibility，不要讓既有主線直接壞掉

## 推薦 write scope

- `src/hpa_mdo/structure/material_proxy_catalog.py`
- `docs/dual_beam_preliminary_material_packages.md`
- `tests/test_material_proxy_catalog.py`

## 完成條件

- material proxy catalog 有更清楚的 recipe family 表達能力
- 測試能驗證新 contract，不只是資料表多幾列
- 文件有明確說清楚哪幾類 recipe 是正式候選、哪幾類只是 local / joint 用途

## 不要做

- 不要直接改 `src/hpa_mdo/utils/discrete_layup.py`
- 不要直接做 spanwise DP search
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
