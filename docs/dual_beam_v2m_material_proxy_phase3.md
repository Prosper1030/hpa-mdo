# Dual-Beam V2.m++ Phase-3 Material / Layup Proxy

產出時間：2026-04-11 CST

## 目的

本階段不是做 full laminate optimization。

目標是在既有 `V2.m++` grouped/discrete 幾何過渡層上，加入少量、工程上合理、可離散化的 material / layup proxy，讓後續 screening 可以回答：

- 哪些材料/疊層 package 值得第一批正式進場
- 哪些 proxy 只該先做 screening，不該直接升格成完整設計軸
- 哪些方向主要買到質量、哪些主要買到 candidate margin / torsion reserve

## 第一批 Proxy 軸

### 1. `main_spar_family`

物理意義：

- 主樑整體 tube family / layup family
- 用少量 package 代表 axial-stiffness-first、balanced HM 等幾種工程可落地 family

形式：

- grouped / discrete

目前 package：

- `main_ref`
- `main_light_ud`
- `main_balanced_hm`

工程理由：

- main plateau 仍然是第一 bending lever，但它已經有幾何 discrete ladder
- 因此 material proxy 不應該再做高維連續化，只需要檢查「同樣幾何下，更輕 UD 偏置」與「更 balanced 但較重」兩類 family 是否有值

### 2. `rear_spar_family`

物理意義：

- 後樑整體 tube family / layup family
- 偏重 rear bending / torsion reserve，而不是大量展開 segment-by-segment layup

形式：

- grouped / discrete

目前 package：

- `rear_ref`
- `rear_balanced_shear`
- `rear_toughened_balance`

工程理由：

- rear 目前不是純質量問題，而是 outboard amplification / reserve 問題
- global rear family 適合先做小 catalog，但不應該一開始就變成大維度 lamination space

### 3. `rear_outboard_reinforcement_pkg`

物理意義：

- 後樑 seg5-6 的局部 sleeve / wrap / layup reserve
- 直接對接 V2.m++ 既有 `rear outboard sleeve` 概念

形式：

- grouped / discrete
- 局部作用於 rear seg5-6
- 使用 tapered mask，不把局部 reinforcement 做成硬跳階 massless knob

目前 package：

- `ob_none`
- `ob_light_wrap`
- `ob_balanced_sleeve`
- `ob_torsion_patch`

工程理由：

- 這是最符合現有 active mode 的第一批 proxy
- 它不改 V2.m++ 幾何 ladder，本質上只是把「rear sleeve」從純 thickness reserve 擴成 material / layup reserve

## 暫時不要獨立進場的軸

### `torsion_oriented_reserve_pkg`

暫不拆成獨立軸。

原因：

- 第一批進場時，最合理的做法是把 torsion-oriented 版本折進 `rear_outboard_reinforcement_pkg` catalog
- 否則會在同一個 rear seg5-6 局部 reserve 上平行長出兩個軸，對現在的 screening 沒必要

### `global_thickness_stiffness_reserve_pkg`

暫不拆成獨立軸。

原因：

- `V2.m++` 已經有 `global_wall_delta_t` 這個 reserve ladder
- Phase-3 的新增維度應先留給真正新的 material / layup proxy，而不是再複製一條與現有 global wall 高度重疊的軸

## 保守接法

### Global family

`main_spar_family` / `rear_spar_family`：

- 走 equivalent + production 兩條路
- 用 effective material package 註冊到 `MaterialDB`
- equivalent gates 會看到這兩個 global family 的改變

### Local rear outboard package

`rear_outboard_reinforcement_pkg`：

- 只作用在 production dual-beam mainline 的 rear seg5-6 element-wise effective properties
- 改變 `E_eff / G_eff / density_eff / allowable_eff`
- 等效 gates 先保留 conservative handling，不把局部好處提前灌進 equivalent gate

這樣的好處是：

- 不重建 solver
- 不回頭動 equivalent / hybrid / old direct 主線策略
- local package 的好處不會被過早放大

## Screening 流程

不要把整個 `V2.m++` 幾何 grid 與所有 material package 做 full Cartesian product。

目前流程：

1. 讀取既有 `V2.m++` selected discrete point
2. 只取少數幾個鄰近幾何 seed
3. 對每個 seed 做小型 package screening
4. 先看哪些 package 在 selected + nearby seeds 上重複出現
5. 只有穩定重複的 package，才考慮升格為正式離散軸

本輪 seed：

- `selected`
- `main_plateau_minus1`
- `rear_general_plus1`
- `rear_outboard_minus1`
- `rear_outboard_plus1`

## 本輪結果

基準點：

- `selected` = `choice=(4,0,0,2,0)`
- tube mass = `10.282 kg`
- `psi_u_all = 2495.830 mm`
- candidate margin = `4.170 mm`

selected geometry 的 one-axis package delta：

- `main_light_ud`: mass `-0.231 kg`, `psi_u_all -40.880 mm`
- `main_balanced_hm`: mass `+0.231 kg`, `psi_u_all +12.145 mm`
- `rear_balanced_shear`: mass `+0.078 kg`, `psi_u_all +10.977 mm`
- `rear_toughened_balance`: mass `+0.130 kg`, `psi_u_all +19.729 mm`
- `ob_light_wrap`: mass `+0.027 kg`, `psi_u_all -21.897 mm`
- `ob_balanced_sleeve`: mass `+0.053 kg`, `psi_u_all -42.446 mm`
- `ob_torsion_patch`: mass `+0.066 kg`, `psi_u_all -13.094 mm`

解讀：

- 如果目標是 **更低質量**，最有值的是 `main_light_ud`
- 如果目標是 **更高 candidate margin / rear reserve**，最有值的是 `ob_balanced_sleeve`
- `rear_spar_family` 這一批 global package 在當前 seed 上沒有顯示出正回報，先不建議升格

Best mass-side feasible candidate：

- geometry = `main_plateau_minus1`
- package = `main_light_ud / rear_ref / ob_none`
- tube mass = `10.013 kg`
- `psi_u_all = 2483.639 mm`
- candidate margin = `16.361 mm`

Best margin-side feasible candidate：

- geometry = `rear_general_plus1`
- package = `main_light_ud / rear_ref / ob_balanced_sleeve`
- tube mass = `10.159 kg`
- `psi_u_all = 2381.617 mm`
- candidate margin = `118.383 mm`

## 工程結論

### 最值得第一批進場

- `rear_outboard_reinforcement_pkg`
- `main_spar_family`

順序上：

1. `rear_outboard_reinforcement_pkg`
2. `main_spar_family`
3. `rear_spar_family` 先保留 screening，不急著升格

### 哪些應該 grouped / discrete

- `main_spar_family`
- `rear_spar_family`
- `rear_outboard_reinforcement_pkg`

這三個第一版都應該是 grouped / discrete，而不是連續化 ply-by-ply。

### 哪些先不要碰

- 獨立 `torsion_oriented_reserve_pkg`
- 獨立 `global_thickness_stiffness_reserve_pkg`
- rib/link 參數
- rib 分布 / 數量 / 厚度
- derivatives
- full laminate schedule optimization

### 現階段最可能買到的是什麼

- `main_spar_family` 最容易買到 **更低質量**
- `rear_outboard_reinforcement_pkg` 最容易買到 **更高 candidate margin / better rear reserve**
- `rear_spar_family` 在目前 V2.m++ 周邊 seed 下，暫時沒有證明值得先買

### 下一步建議

下一步仍然應該是：

- 先做 material proxy screening

不要直接把全部 package 都升格成正式離散軸。

只有下列條件同時成立時，才建議升格：

- 在 `selected` 與至少一個 nearby geometry seed 上都重複有利
- 對 mass 或 candidate margin 的回報明顯
- 沒有把 equivalent gates / geometry validity 推向更脆弱區域

## 總結

這是 rib/link 變數進場前的正確下一步。

因為：

- 它延續 `V2.m++` 的工程抽象層次
- 它不會把設計空間炸開
- 它把最有物理價值的「rear seg5-6 局部 reserve」正式 materialize 成可 screening 的 proxy
- 它比直接跳 rib/link 或 full laminate 更符合目前 repo 的可信度與成熟度
