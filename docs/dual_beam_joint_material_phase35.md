# Dual-Beam Joint Geometry + Material Formal Decision Rules

產出時間：2026-04-12 CST

## 目的

這一輪不再擴 search，不再開新軸。
目標是把目前 joint geometry + material workflow 已經跑出的 Pareto 結果，整理成正式、可自動化的選解規則。

主程式：
[scripts/direct_dual_beam_v2m_joint_material.py](/Volumes/Samsung SSD/hpa-mdo/scripts/direct_dual_beam_v2m_joint_material.py)

對照輸出：

- [report](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow_decision_rules/direct_dual_beam_v2m_joint_material_report.txt)
- [summary](/Volumes/Samsung SSD/hpa-mdo/output/direct_dual_beam_v2m_joint_material_workflow_decision_rules/direct_dual_beam_v2m_joint_material_summary.json)

## Decision Layer 的基本原則

選解只看：

- `Pareto-feasible` candidates
- `mass`
- `psi_u_all`
- `candidate margin`
- 是否使用 `ob_balanced_sleeve`
- 相對 `Primary design` 的重量增量

不引入複雜權重，不做黑箱分數模型。

## 三類正式解

### 1. Primary design

定義：

- 當作預設主解 / release candidate
- 優先不開 `ob_balanced_sleeve`
- 但不能只追最輕，必須有一個簡單 reserve floor

規則：

1. 候選池只看 `Pareto-feasible`
2. 先取 `candidate margin >= 50 mm`
3. 若存在不使用 `ob_balanced_sleeve` 的候選，則只在這個子集合中選
4. 於合格集合中選最輕者
5. tie-break：`psi_u_all` 較低者優先，再看 `candidate margin` 較大者

意思：
Primary 不是最薄的 razor-edge mass-first，而是「仍偏 mass-side、但 reserve 已經過基本工程門檻」的主解。

### 2. Balanced design

定義：

- 當作折衷解
- 只有在 `ob_balanced_sleeve` 真的買到更高 reserve band，而且重量增量還算節制時才成立

規則：

1. 候選池只看 `Pareto-feasible`
2. 必須使用 `ob_balanced_sleeve`
3. 必須滿足 `candidate margin >= 180 mm`
4. 必須滿足 `mass <= Primary mass + 0.250 kg`
5. 於合格集合中選最輕者
6. tie-break：`candidate margin` 較大者優先，再看 `psi_u_all` 較低者

意思：
Balanced 是「值得開 sleeve，但還沒有走到保守端」的正式折衷解。

### 3. Conservative design

定義：

- 當作 reserve-biased / risk-burn-down 解
- 一旦決定開 `ob_balanced_sleeve`，就直接選 margin 最大的非支配解

規則：

1. 候選池只看 `Pareto-feasible`
2. 必須使用 `ob_balanced_sleeve`
3. 選 `candidate margin` 最大者
4. tie-break：較輕者優先，再看 `psi_u_all` 較低者

意思：
Conservative 不再假裝平衡，它就是保守解。

## 套用目前 workflow 的結果

目前 workflow：

- geometry seeds = `31`
- explored candidates = `372`
- wall time = `11.415 s`

### Primary design

- candidate = `(4, 0, 0, 2, 0)` + `main_light_ud / ob_none`
- mass = `10.089649 kg`
- `psi_u_all = 2440.294 mm`
- candidate margin = `59.706 mm`

原因：
它是 Pareto 上最輕、且已達 `50 mm` reserve floor 的 no-sleeve 解。
因此比 razor-edge mass-first 更適合當正式主解。

### Balanced design

- candidate = `(4, 0, 2, 4, 0)` + `main_light_ud / ob_balanced_sleeve`
- mass = `10.302837 kg`
- `psi_u_all = 2315.227 mm`
- candidate margin = `184.773 mm`

原因：
它是唯一同時滿足：

- `ob_balanced_sleeve`
- `candidate margin >= 180 mm`
- `mass <= Primary + 0.250 kg`

的 Pareto candidate。
這讓它成為非常乾淨的折衷解。

### Conservative design

- candidate = `(4, 0, 2, 4, 1)` + `main_light_ud / ob_balanced_sleeve`
- mass = `10.925947 kg`
- `psi_u_all = 2168.143 mm`
- candidate margin = `331.857 mm`

原因：
它是目前 Pareto frontier 上 margin 最大的 `ob_balanced_sleeve` 解，
所以自然對應 conservative tier。

## 工程判斷

### 主解比較接近 mass-first 還是 balanced

比較接近 mass-first，但不是最尖銳的 mass endpoint。

更準確地說：
主解應該是「mass-side with reserve floor」，
而不是「pure minimum-mass regardless of reserve」。

### 什麼 margin 才算夠

以這條 workflow 的第一版 decision layer 來看：

- `~50 mm`：夠當 Primary design 的基本 reserve floor
- `~180 mm`：夠當 Balanced design，代表開 sleeve 有明確工程意義
- `300 mm+`：已進入 Conservative / reserve-biased 區域

### `ob_balanced_sleeve` 什麼情況下值得開

當目標不是只保住 feasible，而是希望：

- 明顯提高 `candidate margin`
- 把解推進到 `180 mm` 以上的較舒適 reserve band
- 且重量增量仍控制在大約 `+0.25 kg` 量級內

就值得開。

### 能不能當自動化 / autoresearch 的第一版 decision layer

可以。

原因：

- 規則簡單
- 門檻明確
- 完全可實作
- 每一步都能向工程團隊解釋
- 不需要複雜調參或黑箱權重

## 下一步建議

下一步最值得做的是：

1. 固化這套選解規則
2. 把它寫成 workflow 輸出的正式 decision layer
3. 之後若要再研究，再小幅調 threshold 或 bridge seeds

現在還不需要把 `rear_spar_family` 拉進來。
更不需要現在跳 rib/link。
