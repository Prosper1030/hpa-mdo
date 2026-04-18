# Task Prompt: Track L Rib Properties Foundation

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**rib integration foundation 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/dual_beam_mainline_theory_spec.md`

## 任務目標

把 rib 從單一 scalar `dual_spar_warping_knockdown` 的手動假設，升成正式的：

- rib family catalog
- spacing / stiffness property contract
- derived `warping_knockdown` helper

這一包的目標是打地基，不是一次把 rib 變成最佳化變數。

## 這包最低要做到的事

- 建立 `data/rib_properties.yaml`
- 能清楚表達 rib family 的：
  - material
  - thickness
  - stiffness proxy
  - spacing guidance
  - notes / intended use
- 建立 derived `warping_knockdown` 的 helper / schema
- 保持 backward compatibility，不要讓現有 config 全部壞掉

## 推薦 write scope

- `data/rib_properties.yaml`
- `src/hpa_mdo/core/config.py`
- `src/hpa_mdo/structure/rib_properties.py`
- `tests/test_rib_properties.py`
- `tests/test_spar_properties_partials.py`

## 完成條件

- repo 不再只能靠手填 `dual_spar_warping_knockdown`
- rib family 有 machine-readable contract
- 測試能驗證 derived knockdown 行為，而不是只有資料檔存在

## 不要做

- 不要碰 `scripts/direct_dual_beam_inverse_design.py`
- 不要碰 `src/hpa_mdo/structure/dual_beam_mainline/**`
- 不要碰 `src/hpa_mdo/hifi/**`
- 不要把 rib 直接變成 outer-loop 設計變數
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
