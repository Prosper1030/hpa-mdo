# Dual-Beam Joint Geometry + Material Search

產出時間：2026-04-11 CST

## 目的

這一步把下列兩個材料 proxy 從 screening 狀態正式升格為主線離散設計軸：

- `main_spar_family`
- `rear_outboard_reinforcement_pkg`

同時維持搜尋空間受控，不做 full Cartesian explosion。

## 搜尋策略

使用 [scripts/direct_dual_beam_v2m_joint_material.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py)：

- 幾何底座：V2.m++ selected point 與 4 個 nearby seeds
- promoted material axes：
  - `main_spar_family` = 3 packages
  - `rear_outboard_reinforcement_pkg` = 4 packages
- 固定 `rear_spar_family = rear_ref`

總搜尋空間：

- `5 geometry seeds x 3 main families x 4 outboard packages = 60 candidates`

這是正式 joint discrete search，但仍然是受控鄰域，不是全域 geometry x material 笛卡兒展開。

## 參考基準：純幾何 V2.m++

參考點來自 [output/direct_dual_beam_v2m_plusplus_compare/direct_dual_beam_v2m_summary.json](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_plusplus_compare/direct_dual_beam_v2m_summary.json)：

- geometry choice = `(4, 0, 0, 2, 0)`
- mass = `10.281877 kg`
- raw main tip = `1776.322 mm`
- raw rear tip = `2494.923 mm`
- raw max `|UZ|` = `2494.923 mm`
- `psi_u_all = 2495.830 mm`
- candidate margin = `4.170 mm`
- wall time = `17.902 s`

## Joint Search 結果

實際執行結果來自：

- [output/direct_dual_beam_v2m_joint_material/direct_dual_beam_v2m_joint_material_report.txt](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material/direct_dual_beam_v2m_joint_material_report.txt)
- [output/direct_dual_beam_v2m_joint_material/direct_dual_beam_v2m_joint_material_summary.json](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material/direct_dual_beam_v2m_joint_material_summary.json)

### Mass-optimal candidate-feasible selected point

- success / feasible = `True / True`
- wall time = `2.315 s`
- geometry choice = `(3, 0, 0, 2, 0)`
- joint choice indices = `(3, 0, 0, 2, 0, 1, 0)`
- `main_spar_family = main_light_ud`
- `rear_outboard_reinforcement_pkg = ob_none`
- mass = `10.050834 kg`
- raw main tip = `1741.000 mm`
- raw rear tip = `2467.820 mm`
- raw max `|UZ|` = `2467.820 mm`
- `psi_u_all = 2468.760 mm`
- candidate margin = `31.240 mm`
- hard feasible / candidate feasible = `True / True`

相對純幾何 V2.m++：

- mass `-0.231 kg`
- `psi_u_all -27.070 mm`
- candidate margin `+27.070 mm`
- wall time `-15.587 s`

### Best margin-side candidate-feasible point

- geometry choice = `(4, 0, 1, 2, 0)`
- `main_spar_family = main_light_ud`
- `rear_outboard_reinforcement_pkg = ob_balanced_sleeve`
- mass = `10.197937 kg`
- `psi_u_all = 2374.200 mm`
- candidate margin = `125.800 mm`

## 工程解讀

1. `main_spar_family` 已被正式證明值得保留
   `main_light_ud` 在所有 5 個 geometry seeds 上都成為 mass-first 的最佳 promoted family。

2. `rear_outboard_reinforcement_pkg` 已被正式證明值得保留
   `ob_balanced_sleeve` 雖然不是 mass-optimal selected point，但它明確是 margin-side 最有效的 local reserve package。

3. geometry + material 聯合後，比純幾何 V2.m++ 更接近想要的方向
   不只減重，candidate margin 也同步變好，而且搜尋成本沒有暴增。

4. 下一步仍應優先深化 geometry + material 聯合策略
   `rear_spar_family` 仍不必先升格；`rib/link` 更應該晚於這一步。
