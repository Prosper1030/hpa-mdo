# Task Prompt: Track N Passive Rib Robustness Mode

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**dual-beam rib robustness 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/dual_beam_mainline_theory_spec.md`

## 前提

這一包只有在 **Track L rib properties foundation 已經 merge / verify** 之後才應開始。

## 任務目標

把 repo 從 current parity / offset-rigid rib assumptions，往更合理的 **passive rib robustness compare path** 推進。

這一包的角色是 robustness / sensitivity，不是直接把 finite-rib mode 升成主線 sign-off truth。

## 這包最低要做到的事

- 建立 passive rib robustness compare path
- 能比較：
  - current parity
  - 更接近 physical rib 的 compare mode
- 測試能驗證新 mode 不只是 enum 存在，而是真的能被主線 dual-beam mainline 使用

## 推薦 write scope

- `src/hpa_mdo/structure/dual_beam_mainline/types.py`
- `src/hpa_mdo/structure/dual_beam_mainline/constraints.py`
- `src/hpa_mdo/structure/dual_beam_mainline/rib_link.py`
- `tests/test_dual_beam_mainline.py`

## 完成條件

- repo 有 passive rib robustness mode
- 可以做 parity vs finite-rib 的 sensitivity compare
- 有最小必要測試

## 不要做

- 不要碰 `scripts/direct_dual_beam_inverse_design.py`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要把這一包包裝成 final validation truth
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
