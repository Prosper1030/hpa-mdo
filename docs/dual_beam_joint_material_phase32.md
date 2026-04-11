# Dual-Beam Joint Geometry + Material Search Expansion

產出時間：2026-04-12 CST

## 目的

在既有的 joint geometry + material 主線上，把搜尋策略從 compact 鄰域擴成受控的 expanded 鄰域，用來回答三件事：

- 好結果是不是只出現在單一 seed
- 能不能再找到更輕的 feasible 解
- 能不能整理出 `mass-first`、`margin-first`、`balanced compromise` 三種可代表的工程解

這一步仍然維持：

- 只升格 `main_spar_family`
- 只升格 `rear_outboard_reinforcement_pkg`
- 固定 `rear_spar_family = rear_ref`
- 不做 full Cartesian explosion

## 搜尋策略

主程式：
[scripts/direct_dual_beam_v2m_joint_material.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py)

策略分兩層：

- `compact`
  - `5` 個 geometry seeds
  - `5 x 3 x 4 = 60` candidates
- `expanded`
  - `17` 個 geometry seeds
  - 包含 selected point、有效的一階鄰點、少量二階檢查、以及 6 個 pairwise couplings
  - `17 x 3 x 4 = 204` candidates

對照輸出：

- compact:
  [report](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_compact_check/direct_dual_beam_v2m_joint_material_report.txt)
  [summary](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_compact_check/direct_dual_beam_v2m_joint_material_summary.json)
- expanded:
  [report](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_expanded_check/direct_dual_beam_v2m_joint_material_report.txt)
  [summary](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_expanded_check/direct_dual_beam_v2m_joint_material_summary.json)

## 參考基準

純幾何 V2.m++ selected point：

- geometry choice = `(4, 0, 0, 2, 0)`
- mass = `10.281877 kg`
- raw main tip = `1776.322 mm`
- raw rear tip = `2494.923 mm`
- raw max `|UZ|` = `2494.923 mm`
- `psi_u_all = 2495.830 mm`
- candidate margin = `4.170 mm`

## Expanded 代表解

### Mass-first feasible

- geometry choice = `(3, 0, 0, 1, 0)`
- material choice = `main_light_ud / ob_none`
- mass = `10.028424 kg`
- raw main tip = `1744.069 mm`
- raw rear tip = `2485.807 mm`
- raw max `|UZ|` = `2485.807 mm`
- `psi_u_all = 2486.697 mm`
- candidate margin = `13.303 mm`

相對 pure geometry V2.m++：

- mass `-0.253 kg`
- `psi_u_all -9.133 mm`
- candidate margin `+9.133 mm`

### Margin-first feasible

- geometry choice = `(4, 0, 0, 2, 1)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.759374 kg`
- raw main tip = `1593.146 mm`
- raw rear tip = `2251.557 mm`
- raw max `|UZ|` = `2251.557 mm`
- `psi_u_all = 2252.888 mm`
- candidate margin = `247.112 mm`

相對 pure geometry V2.m++：

- mass `+0.477 kg`
- `psi_u_all -242.942 mm`
- candidate margin `+242.942 mm`

### Balanced Compromise

- geometry choice = `(4, 0, 2, 2, 0)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.253105 kg`
- raw main tip = `1698.835 mm`
- raw rear tip = `2343.310 mm`
- raw max `|UZ|` = `2343.310 mm`
- `psi_u_all = 2344.594 mm`
- candidate margin = `155.406 mm`

相對 pure geometry V2.m++：

- mass `-0.029 kg`
- `psi_u_all -151.236 mm`
- candidate margin `+151.236 mm`

## 與 compact 對照

compact 代表點：

- mass-first = `(3, 0, 0, 2, 0)` + `main_light_ud / ob_none`
  - `10.050834 kg`
  - `psi_u_all = 2468.760 mm`
  - margin = `31.240 mm`
- margin-first = `(4, 0, 1, 2, 0)` + `main_light_ud / ob_balanced_sleeve`
  - `10.197937 kg`
  - `psi_u_all = 2374.200 mm`
  - margin = `125.800 mm`
- balanced = `(4, 0, 0, 3, 0)` + `main_light_ud / ob_balanced_sleeve`
  - `10.166623 kg`
  - `psi_u_all = 2389.358 mm`
  - margin = `110.642 mm`

expanded 帶來的新增訊息：

1. 更輕的 feasible 點確實存在
   `expanded mass-first` 比 compact mass-first 再輕 `0.022 kg`。

2. 更大的 margin-side 點也確實存在
   `expanded margin-first` 比 compact margin-first 再多 `121.312 mm` margin。

3. `balanced compromise` 也更清楚
   `expanded balanced` 只比 pure geometry 重量改善小一點，但把 margin 大幅拉高到 `155.406 mm`。

## 材料軸角色

1. `main_spar_family`
   在 expanded `17` 個 geometry-best rows 裡，全部都是 `main_light_ud`。
   這個軸目前的角色已經很清楚：主打 mass efficiency，是正式主線保留變數。

2. `rear_outboard_reinforcement_pkg`
   在每個 geometry seed 的 mass-best feasible 選擇裡，都是 `ob_none`。
   但在 margin-first 與 balanced representative 裡，`ob_balanced_sleeve` 都成為最佳解。
   這個軸的角色也變得很清楚：不是拿來搶最輕，而是拿來買局部 reserve 與 candidate margin。

## 工程判斷

- 這條 joint geometry + material strategy 現在是穩的
  好結果沒有消失，expanded 反而把三種代表解拉得更清楚。

- `main_spar_family` 與 `rear_outboard_reinforcement_pkg` 都值得保留成正式主線變數
  前者是減重軸，後者是 reserve / margin 軸。

- 下一步最該做的是繼續擴 joint strategy，但要維持受控
  先沿著這條 geometry + material 聯合路徑，把 seed strategy 與 representative ranking 再打磨一輪；
  `rear_spar_family` 仍然排在後面，`rib/link` 更後面。
