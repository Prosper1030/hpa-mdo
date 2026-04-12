# Dual-Beam Joint Geometry + Material Workflow Formalization

產出時間：2026-04-12 CST

## 目的

這一輪不是換主題，而是把既有的 joint geometry + material 聯合策略整理成更像正式 workflow：

- 不新增材料軸
- 不升格 `rear_spar_family`
- 不碰 rib/link
- 不做 derivatives / laminate optimization / full Cartesian explosion

主程式：
[scripts/direct_dual_beam_v2m_joint_material.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py)

對照輸出：

- [report](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow/direct_dual_beam_v2m_joint_material_report.txt)
- [summary](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow/direct_dual_beam_v2m_joint_material_summary.json)

## Workflow 定義

這次把 joint strategy 明確拆成兩階段：

1. `expanded discovery`
   以既有 V2.m++ selected point 為中心，先跑 `17` 個受控 geometry seeds。

2. `representative support neighborhoods`
   針對 discovery 找到的 `mass-first`、`margin-first`、`balanced` 三個代表解，再各自補 compact local neighborhood；
   去重之後新增 `9` 個 geometry seeds。

總計：

- geometry seeds = `26`
- explored candidates = `26 x 3 x 4 = 312`
- wall time = `11.687 s`

## 三個正式代表解

### 1. Mass-first feasible

- geometry choice = `(3, 0, 0, 1, 0)`
- material choice = `main_light_ud / ob_none`
- mass = `10.028424 kg`
- raw main tip = `1744.069 mm`
- raw rear tip = `2485.807 mm`
- raw max `|UZ|` = `2485.807 mm`
- `psi_u_all = 2486.697 mm`
- candidate margin = `13.303 mm`

### 2. Margin-first feasible

- geometry choice = `(4, 0, 1, 2, 1)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.817926 kg`
- raw main tip = `1588.353 mm`
- raw rear tip = `2221.441 mm`
- raw max `|UZ|` = `2221.441 mm`
- `psi_u_all = 2222.895 mm`
- candidate margin = `277.105 mm`

### 3. Balanced compromise

- geometry choice = `(4, 0, 2, 3, 0)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.278004 kg`
- raw main tip = `1695.468 mm`
- raw rear tip = `2328.188 mm`
- raw max `|UZ|` = `2328.188 mm`
- `psi_u_all = 2329.530 mm`
- candidate margin = `170.470 mm`

## 穩定性判讀

這次不是只看單點，而是看代表區域在 workflow 擴充後是否還成立。

### `main_spar_family`

- 全部 `43` 個 Pareto-feasible candidates 都是 `main_light_ud`
- `mass-first` / `margin-first` / `balanced` 三個代表區域的 local Pareto main family 也全部是 `main_light_ud`

判讀：
`main_spar_family` 的角色已經固定，現在就是明確的減重主軸。

### `rear_outboard_reinforcement_pkg`

- `mass-first` 端點仍然是 `ob_none`
- `margin-first` 端點仍然是 `ob_balanced_sleeve`
- `balanced` 端點也仍然是 `ob_balanced_sleeve`
- `ob_light_wrap` 仍然存在於 Pareto frontier 中段，但在 margin / balanced 端沒有取代 `ob_balanced_sleeve`

代表區域摘要：

- mass-first region:
  `5` 個 geometry choices、`32` 個 feasible candidates、`9` 個 local Pareto candidates
- margin-first region:
  `3` 個 geometry choices、`36` 個 feasible candidates、`8` 個 local Pareto candidates
- balanced region:
  `3` 個 geometry choices、`36` 個 feasible candidates、`7` 個 local Pareto candidates

判讀：
`rear_outboard_reinforcement_pkg` 的角色也已固定。
`ob_none` 是 mass-side 選擇；`ob_balanced_sleeve` 是 reserve / margin-side 正式選擇。

## 工程判斷

### 1. 這條 joint geometry + material strategy 現在夠不夠穩

夠穩。

理由不是只因為三個代表點還在，而是因為：

- workflow 擴到 `312` 個 candidates 後，三種 archetype 都沒有消失
- `main_light_ud` 在整條 Pareto frontier 上完全主導
- `ob_balanced_sleeve` 在 margin-side 與 balanced-side 仍然穩定勝出
- 各 archetype 周邊都有多個 feasible / Pareto 支持點，不是單一孤立解

### 2. 目前最值得保留的正式材料軸是不是仍然這兩個

是。

- `main_spar_family`
- `rear_outboard_reinforcement_pkg`

這兩個軸現在已經足夠明確，暫時不需要太早把 `rear_spar_family` 拉進主線。

### 3. 下一步最該做什麼

優先順序應該是：

1. 再小幅擴 joint strategy
2. 再更後面才考慮 `rear_spar_family`
3. `rib/link` 更後面

更具體地說，下一步仍應留在 joint geometry + material 這條路上，把 workflow 的局部 seed policy 再往 margin / balanced ridge 補一小圈，而不是現在就開新材料軸或跳到 rib/link。
