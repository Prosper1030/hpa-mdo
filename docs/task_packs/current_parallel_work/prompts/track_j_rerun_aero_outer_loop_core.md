# Task Prompt: Track J Rerun-Aero Outer-Loop Core

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**主線 Phase 2 核心任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `scripts/direct_dual_beam_inverse_design.py`

## 任務目標

把外圈從：

`reuse existing VSPAero AoA sweep + light refresh`

往：

`candidate-level geometry rebuild + rerun-aero contract`

推進。

這一包是 **core contract 任務**，不是一次把 full trim loop-closure 全做完。

## 這包最低要做到的事

- 每個外圈 candidate 有明確的 rerun-aero code path
- summary / artifact 能明確區分：
  - legacy refresh path
  - rebuilt-geometry / rerun-aero path
- candidate 的 aero loads 不再只能來自既有 AoA case 插值
- 至少建立清楚的 load ownership / artifact ownership 說明

## 推薦 write scope

- `scripts/direct_dual_beam_inverse_design.py`
- `src/hpa_mdo/aero/vsp_builder.py`
- `src/hpa_mdo/aero/vsp_aero.py`
- `src/hpa_mdo/aero/load_mapper.py`
- `tests/test_inverse_design.py`

## 完成條件

- outer-loop core 有 candidate-level rerun-aero contract
- report / summary 能清楚說明目前 candidate 是哪種 aero source
- 有最小必要測試，不要只改報告字串

## 不要做

- 不要碰 `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- 不要碰 `scripts/dihedral_sweep_campaign.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要碰 `src/hpa_mdo/utils/discrete_layup.py`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`

## 額外提醒

- 這一波的目標是把 rerun-aero contract 立起來，不是一次做到 full aeroelastic sign-off
- 可以保留 legacy refresh path 做回歸比較，但不能讓新 contract 只停在文件敘述
