# Dual-Beam Preliminary Material Packages

產出時間：2026-04-11 CST

## 範圍

這份 Phase 3.1 交付不是 full laminate optimization，也不是 geometry x material 全笛卡兒搜尋。

本次正式建立的是：

- `main_spar_family` 的 preliminary grouped/discrete property table
- `rear_outboard_reinforcement_pkg` 的 preliminary grouped/discrete property table
- 明寫的 buckling-aware / conservative rules
- 可供後續正式升格與校準的 loader / lookup / registration 介面

`rear_spar_family` 仍保留在同一份 catalog 中，但目前狀態是 `screening_only`，不視為本階段正式升格對象。

## 數值定義方式

所有 package 定義集中在 [data/dual_beam_material_packages.yaml](/Volumes/Samsung SSD/hpa-mdo/data/dual_beam_material_packages.yaml)。

載入與 lookup 介面位於 [src/hpa_mdo/structure/material_proxy_catalog.py](/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/material_proxy_catalog.py)。

目前表中的 resolved 數值是以：

- base material = `carbon_fiber_hm`
- material safety factor = `1.5`

所得到的第一版 engineering estimate。

因此：

- `E_eff` / `G_eff`：是 beam-level equivalent property 的 preliminary engineering estimate
- `density_eff`：是把 tube/sleeve 額外壁厚與 resin penalty 壓成等效密度後的 preliminary estimate
- `allowable_eff`：是 common HM baseline allowables 經 package uplift 與 conservative knockdown 後，再除以 `material_safety_factor`

## `main_spar_family`

| key | label | 0 / +/-45 / 90 | E_eff (GPa) | G_eff (GPa) | density_eff (kg/m3) | allowable_eff (MPa) | 備註 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `main_ref` | Baseline/reference | 60 / 30 / 10 | 230.0 | 15.0 | 1600 | 1000.0 | 現行 HM 參考族；balanced + symmetric |
| `main_light_ud` | Light UD / axial-dominant | 72 / 18 / 10 | 239.2 | 14.25 | 1560 | 930.0 | 較輕、較偏 0°，但對 shear / local stability 較保守 |
| `main_balanced_hm` | Balanced HM | 55 / 30 / 15 | 227.7 | 16.5 | 1648 | 1008.8 | 較重但給更多 shear / hoop reserve |

工程判讀：

- `main_light_ud` 是目前最合理的 mass-side 正式候選
- `main_balanced_hm` 是目前最合理的 reserve-side 正式候選
- 三者都保留 balanced + symmetric，且不允許把 90° 砍到 0

## `rear_outboard_reinforcement_pkg`

這個軸的 layup 比例是指「added overlay only」，不是整根 rear spar 的全厚度 family。

| key | label | added 0 / +/-45 / 90 | E_eff (GPa) | G_eff (GPa) | density_eff (kg/m3) | allowable_eff (MPa) | 物理意義 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `ob_none` | None | 0 / 0 / 0 | 230.0 | 15.0 | 1600 | 1000.0 | 無局部補強；完全繼承 base rear family |
| `ob_light_wrap` | Light wrap | 15 / 65 / 20 | 236.9 | 17.1 | 1664 | 969.0 | 單層輕量 braided sleeve + hoop keeper 的等效包 |
| `ob_balanced_sleeve` | Balanced sleeve | 25 / 50 / 25 | 243.8 | 18.6 | 1728 | 1017.6 | 本輪最值得正式升格的 local sleeve/wrap package |
| `ob_torsion_patch` | Torsion patch | 10 / 75 / 15 | 230.0 | 20.1 | 1744 | 940.0 | 局部扭轉熱點 patch，偏 shear/torsion 而非通用 reserve |

工程判讀：

- `ob_balanced_sleeve` 是目前最值得正式升格的 local reinforcement package
- `ob_light_wrap` 可以保留作較低成本、較低質量的第一層 reserve
- `ob_torsion_patch` 合理，但應維持在 outboard non-joint hot spot 才使用，不應當作抽象全域倍率

## Buckling-aware / Conservative Rules

以下規則已經進入 package catalog，而不是只留在文件註解裡：

1. 最低 90°/hoop 比例
   `main_ref` / `main_light_ud` 至少 10%，`main_balanced_hm` 至少 15%。
   `ob_light_wrap` 至少 20%，`ob_balanced_sleeve` 至少 25%，`ob_torsion_patch` 至少 15%。

2. 外層不能用純 0°
   `main_spar_family` 三個 package 都禁止 outer pure axial。
   `rear_outboard_reinforcement_pkg` 中的 `ob_light_wrap` / `ob_balanced_sleeve` / `ob_torsion_patch` 也都禁止 outer pure axial。

3. conservative knockdown
   `main_light_ud`：`0.93`
   `main_balanced_hm`：`0.97`
   `ob_light_wrap`：`0.95`
   `ob_balanced_sleeve`：`0.96`
   `ob_torsion_patch`：`0.94`

4. 區域限制
   `main_spar_family` 仍是 global family。
   `rear_outboard_reinforcement_pkg` 的三個非零 package 都限制在 `rear_seg5_6_outboard_non_joint_only`。

5. local buckling reserve 標記
   `main_balanced_hm`：`moderate`
   `ob_light_wrap`：`moderate`
   `ob_balanced_sleeve`：`high`
   `ob_torsion_patch`：`moderate`

6. equivalent gate 接法
   `main_spar_family` / `rear_spar_family` 仍可走 `full_global` equivalent + production。
   `rear_outboard_reinforcement_pkg` 明確標記為 `production_local_only`，避免把 local sleeve 的好處過早灌進 equivalent gate。

## 哪些值仍是 provisional

目前最明確仍屬 provisional 的，不是 package 名稱本身，而是下列數值映射：

- `E_eff` / `G_eff` 對應的 scale，仍是 engineering estimate，不是經完整 CLT + coupon + subcomponent 校準後的真值
- `density_eff` 將 sleeve 額外壁厚、resin、consolidation penalty 壓成等效密度，後續需要對實際製程再校準
- `allowable_eff` 雖然已乘上 conservative knockdown，但仍未經 joint coupon / local buckling / defect sensitivity 對照
- `local_buckling_reserve` 目前是 package logic 裡的保守標記，不是 validated composite buckling model

## 最需要再校準的項目

1. `rear_outboard_reinforcement_pkg` 的 `G_eff` uplift
   因為 sleeve/patch 真正的效果同時來自 material、wall addition、以及局部幾何變化；目前模型把它壓成等效 material scale。

2. `rear_outboard_reinforcement_pkg` 的 `density_eff`
   目前是把局部加層與 resin penalty 等效成密度增量，這對 mass 方向的誤差最敏感。

3. `main_light_ud` 的 `allowable_eff`
   這個 family 最容易帶來 mass advantage，但也最容易高估壓縮側/local stability。

4. `ob_torsion_patch` 的 knockdown
   patch termination、out-of-plane local field 與 defect sensitivity 目前都還沒被獨立驗證。

## 本步完成後的工程結論

- `main_spar_family`：已具備足夠合理的 preliminary material data，可正式升格
- `rear_outboard_reinforcement_pkg`：已具備足夠合理的 preliminary material data，可正式升格
- `rear_spar_family`：仍維持 screening-only，不建議這一輪一起升格

這代表下一步可以進入：

- 兩個正式材料軸的升格
- 小型 geometry + material 聯合離散優化

但仍不建議直接跳到：

- full geometry x material 笛卡兒爆炸搜尋
- full laminate optimization
- rear_spar_family 正式升格

## 正式 recipe family foundation

這份 catalog 現在不只是在列 package，也明確把 package 對齊到功能型 recipe family。

正式 family key 如下：

| family key | 定義 | 目前代表 package | 目前定位 |
| --- | --- | --- | --- |
| `bending_dominant` | 以 0°/軸向效率為主，優先買 bending efficiency / mass | `main_light_ud` | 正式 global candidate |
| `balanced_torsion` | 保留較強 +/-45 與 hoop 參與，優先買 torsion / reserve | `main_balanced_hm`, `rear_balanced_shear`, `rear_toughened_balance`, `ob_torsion_patch` | `main_balanced_hm` 是正式 global candidate；rear family 仍是 screening-only；`ob_torsion_patch` 是 local-only |
| `joint_hoop_rich_local` | 以 sleeve / hoop-rich local reserve 為主，服務 joint / local hotspot | `ob_light_wrap`, `ob_balanced_sleeve` | 正式 local/joint 用途，不是 global family candidate |
| `reference_baseline` | 基準/對照 package | `main_ref`, `rear_ref`, `ob_none` | reference only |

這個分類的目的不是現在就做 full selector，而是先讓 catalog 層能清楚回答：

- 這個 package 是哪一類 recipe？
- 它是正式 candidate、screening-only，還是 local/joint only？
- 後續 selector / outer loop 在 lookup 時，應該把它放在哪個角色上理解？

## Property-row / lookup contract

catalog API 現在有兩層向後相容 contract：

1. `resolve_catalog_property_rows(...)`
   維持原本 axis -> rows 的回傳形式，但每個 row 現在都會帶：
   - `lookup_key`：穩定鍵，格式為 `axis:package_key`
   - `recipe_profile.family.key`
   - `recipe_profile.role_key`

2. `resolve_catalog_lookup_rows(...)` / `build_catalog_lookup_index(...)`
   提供扁平化 lookup 介面，方便後續 selector / report / outer-loop 直接用 stable key 或 recipe family 篩選。

目前 `role_key` 的工程意義：

- `formal_candidate`
  代表可以當成正式全域候選，接到後續 selector / outer-loop candidate comparison。
- `screening_only`
  代表可留在小範圍 screening 或研究比較，但不是本波正式 promotion 對象。
- `local_reinforcement_only`
  代表只能當 local / joint / hotspot reinforcement，不能被誤當成 global family。
- `reference_only`
  代表是 baseline / no-overlay / continuity 用的對照鍵。

這個 contract 的重點是：

- 不需要先動 `discrete_layup.py`，就能先把 recipe library 的語意固定下來。
- 後續如果要做 property-based selector，可以直接用 `family.key` + `role_key` 決定哪些 package 進候選池。
- local sleeve / patch 不會再和 global family 混成同一種抽象材料軸。
