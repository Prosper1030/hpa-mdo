# Dual-Beam Joint Geometry + Material Workflow Ridge Refinement

產出時間：2026-04-12 CST

## 目的

這一輪只做一件事：
沿著既有 `margin / balanced` ridge 再補非常少量的受控 geometry seeds，確認 Pareto 結構與三個代表區域是不是更像正式 workflow。

維持不變：

- 不重建主線
- 不改 STEP export
- 不新增材料軸
- 不碰 `rear_spar_family`
- 不碰 rib/link
- 不做 derivatives

主程式：
[scripts/direct_dual_beam_v2m_joint_material.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py)

對照輸出：

- [report](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow_ridge_check/direct_dual_beam_v2m_joint_material_report.txt)
- [summary](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow_ridge_check/direct_dual_beam_v2m_joint_material_summary.json)

## Workflow 變更

在既有 workflow 的兩階段之後，加上一個非常小的第 3 階段：

1. `expanded discovery`：`17` 個 geometry seeds
2. `representative support neighborhoods`：`9` 個 geometry seeds
3. `ridge refinement`：只補 `5` 個 geometry seeds

這 `5` 個新 seeds 全部只落在 margin / balanced branch：

- `(4, 0, 2, 2, 1)`
- `(4, 0, 1, 3, 1)`
- `(4, 0, 2, 3, 1)`
- `(4, 0, 2, 4, 0)`
- `(4, 0, 2, 4, 1)`

總計：

- geometry seeds = `31`
- explored candidates = `31 x 3 x 4 = 372`
- wall time = `12.095 s`

## 更新後的三種代表解

### Mass-first feasible

- geometry choice = `(3, 0, 0, 1, 0)`
- material choice = `main_light_ud / ob_none`
- mass = `10.028424 kg`
- raw main tip = `1744.069 mm`
- raw rear tip = `2485.807 mm`
- raw max `|UZ|` = `2485.807 mm`
- `psi_u_all = 2486.697 mm`
- candidate margin = `13.303 mm`

### Margin-first feasible

- geometry choice = `(4, 0, 2, 4, 1)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.925947 kg`
- raw main tip = `1577.185 mm`
- raw rear tip = `2166.437 mm`
- raw max `|UZ|` = `2166.437 mm`
- `psi_u_all = 2168.143 mm`
- candidate margin = `331.857 mm`

### Balanced compromise

- geometry choice = `(4, 0, 2, 4, 0)`
- material choice = `main_light_ud / ob_balanced_sleeve`
- mass = `10.302837 kg`
- raw main tip = `1692.112 mm`
- raw rear tip = `2313.829 mm`
- raw max `|UZ|` = `2313.829 mm`
- `psi_u_all = 2315.227 mm`
- candidate margin = `184.773 mm`

## 這輪新增訊息

1. `margin-first` 不只是存在，而是沿 ridge 再往上延伸
   代表點從 `(4, 0, 1, 2, 1)` 推進到 `(4, 0, 2, 4, 1)`，
   candidate margin 從 `277.105 mm` 提升到 `331.857 mm`。

2. `balanced` 區域也更清楚
   代表點從 `(4, 0, 2, 3, 0)` 推進到 `(4, 0, 2, 4, 0)`，
   candidate margin 從 `170.470 mm` 提升到 `184.773 mm`，
   仍然維持明確的中間 tradeoff 角色。

3. Pareto frontier 更像連續結構而不是偶然點
   Pareto-feasible candidates 從 `43` 增加到 `55`，
   而且新增點正好接在原本的 margin / balanced ridge 上。

## 材料軸角色

### `main_spar_family`

- 全部 `55` 個 Pareto-feasible candidates 都是 `main_light_ud`

判讀：
這個軸的角色已經完全固定，就是減重主軸。

### `rear_outboard_reinforcement_pkg`

- `mass-first` 仍然是 `ob_none`
- `margin-first` 仍然是 `ob_balanced_sleeve`
- `balanced` 也仍然是 `ob_balanced_sleeve`
- `ob_light_wrap` 仍然只留在中段 Pareto 過渡帶

判讀：
這個軸的角色也已經非常固定。
`ob_none` 是 mass-side；
`ob_balanced_sleeve` 是 margin / balanced-side 正式解。

## 工程判斷

### 1. 這條 workflow 現在是不是已經夠穩

是，已經相當穩。

原因：

- 三個代表區域都還在
- margin / balanced ridge 在小幅擴充後變得更連續
- Pareto frontier 從 `43` 擴到 `55`，新增點沒有改寫主結論，反而讓結構更清楚

### 2. `main_spar_family` 和 `rear_outboard_reinforcement_pkg` 的角色有沒有完全固定

可以說已經固定了。

- `main_spar_family` = `main_light_ud` 主導整條 Pareto frontier
- `rear_outboard_reinforcement_pkg` = `ob_none` 對 mass-side，`ob_balanced_sleeve` 對 margin / balanced-side

### 3. 下一步最該做什麼

仍然是：

1. 再小幅擴 joint strategy
2. `rear_spar_family` 之後再說
3. rib/link 更後面

下一步比較合理的是繼續用同一種受控 workflow，沿 ridge 再補極少量 bridge seeds 或做 representative ranking/selection cleanup，而不是現在就把新材料軸或 rib/link 拉進來。
