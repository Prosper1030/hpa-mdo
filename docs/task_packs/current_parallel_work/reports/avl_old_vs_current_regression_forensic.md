# AVL Old-vs-Current Regression Forensic

> 文件性質：old-vs-current AVL regression forensic
> 任務日期：2026-04-19
> 任務目標：回答「為什麼舊 AVL pass case (`x4.0`, `exp=1.0`) 以前可以過，但現在 repaired AVL-first path 的同名設定會卡 `trim_aoa_exceeds_limit`」

## 0. Post-Fix Update

- **這份報告下面的大部分內容，記錄的是 pre-fix 狀態下的 regression forensic。**
- 後續已另外修掉三件事：
  - `blackcat_004` 主翼 airfoil mapping / baseline AVL 與 reference `.vsp3` 對齊
  - `CL required` 改成使用 generated candidate `case.avl` 的 `Sref`
  - `lift_total_n` 與 `min_lift_n` 的近等值比較補上數值容差，避免 AVL 輸出四捨五入造成假 `insufficient_lift`
- 修正後我用同一條 repaired AVL-first 路徑，對 `x4.0 / exp=1.0` 做最小必要 rerun：
  - output: `/private/tmp/track_z_avl_exp1_x4_postfix_tol_20260419`
  - `CL required = 1.077710452`
  - `Alpha = 10.16612 deg`
  - `L/D = 44.03`
  - beta / directional / spiral checks: `ok`
  - structural follow-on: `feasible`
  - mass: `21.740 kg`
  - clearance: `58.036 mm`
  - final reject reason: `none`
- 也就是說：
  - **這份報告原本追到的 `trim_aoa_exceeds_limit` regression，如今已在 post-fix rerun 中解除。**
  - 現在保留這份報告的價值，主要是讓後續知道 pre-fix failure chain 當時到底是怎麼形成的。

## 1. 結論先講

- 註：本節結論是 **pre-fix** forensic 結論，不代表目前 head 狀態仍然如此。
- **舊 `x4.0 / exp=1.0` pass case 並不是主要因為 current 幾何 baseline 變差才消失。**
- 這次 regression 的主因是：
  - **current repaired path 的 `cl_required` 仍然用 `scripts/dihedral_sweep_campaign.py` 內的 trapezoid proxy area**
    - `estimate_reference_area(cfg) = 0.5 * span * (root_chord + tip_chord)`
  - 但 current AVL case file 已經換成 **VSP-calibrated multi-station baseline**
    - `Sref = 35.175`
    - `Cref = 1.13017474`
    - `Xref = 0.282543685`
- 也就是說，**current gate 在用 `28.6275 m^2` 算 `cl_required`，但 AVL 真正跑的 case header 是 `35.175 m^2`。**
- 這個 reference-area contract 不一致，直接把 required CL 從：
  - `1.2352058` 拉到 `1.3241975`
- 對 `x4.0 / exp=1.0` 而言：
  - 舊 case trim AoA：`11.56845 deg`
  - current case 在 **舊 CL target** 下重跑：`11.67279 deg`
  - current repaired gate 真正要求的 trim AoA：`12.52845 deg`
- 所以這 `+0.96 deg` 的 regression 裡，大約：
  - **`+0.104 deg`** 是 current baseline 幾何 / aero 差異本身
  - **`+0.856 deg`** 是 current gate reference-area mismatch 額外硬加出來的
- 換句話說，**約 `89%` 的 AoA regression 是 gate contract 問題，不是 baseline 幾何本身把舊可行設計空間洗掉。**

## 2. 這次比對用的固定證據

### 2.1 舊 pass case

- `output/_archive_pre_2026_04_15/dihedral_sweep_phase9a_extension/mult_4p000/case.avl`
- `output/_archive_pre_2026_04_15/dihedral_sweep_phase9a_extension/mult_4p000/case_trim.ft`
- `output/_archive_pre_2026_04_15/dihedral_sweep_phase9a_extension/mult_4p000/avl_trim_stdout.log`
- `output/_archive_pre_2026_04_15/dihedral_sweep_phase9a_extension/mult_4p000/case_metadata.json`

### 2.2 current repaired path

- `data/blackcat_004_full.avl`
- `/tmp/track_z_avl_exp1_fullgate_20260419/mult_4p000/case.avl`
- `/tmp/track_z_avl_exp1_fullgate_20260419/mult_4p000/case_trim.ft`
- `/tmp/track_z_avl_exp1_fullgate_20260419/mult_4p000/avl_trim_stdout.log`
- `/tmp/track_z_avl_exp1_fullgate_20260419/mult_4p000/case_metadata.json`
- `output/track_u_candidate_avl_smoke_20260419/mult_4p000/case.avl`
- `/private/tmp/track_z_avl_exp1_x4_postfix_20260419/mult_4p000/case.avl`
- `/private/tmp/track_z_avl_exp1_x4_postfix_tol_20260419/mult_4p000/case.avl`
- `docs/task_packs/current_parallel_work/reports/avl_baseline_exponent_rebaseline_report.md`

### 2.3 code-level formula check

- `scripts/dihedral_sweep_campaign.py`
  - `estimate_reference_area(cfg)` uses `0.5 * span * (root_chord + tip_chord)`
  - campaign `cl_required` uses that proxy area, not the AVL case header `Sref`

### 2.4 這次真正的 VSP parser / builder 問題是什麼

- 這次 **不是** `vsp_introspect.summarize_vsp_surfaces()` 把 reference `.vsp3` 的 root / tip 讀反。
- 針對真實 reference `.vsp3`
  - `/Volumes/Samsung SSD/SyncFile/Aerodynamics/black cat 004 wing only/blackcat 004 wing only.vsp3`
  - introspection 讀到的主翼 airfoil 本來就是：
    - `y = 0.0 ~ 13.5 m`：`fx76mp140`
    - `y = 16.5 m`：`clarkysm`
- 真正出問題的是三層 drift 疊在一起：
  - config `airfoil_root / airfoil_tip` 一度寫反
  - `data/blackcat_004_full.avl` 的主翼 `AFILE` 一度寫反
  - `VSPBuilder._extract_reference_wing_schedule()` 一度先用 `_airfoil_for_eta()` 的簡化 fallback seed schedule，再去補 reference VSP airfoils
- 所以這次更準確的說法不是「VSP parser 讀壞」，而是：
  - **reference `.vsp3` truth、config defaults、baseline AVL、reference-schedule builder 之間一度不一致。**

## 3. 舊 pass case 與 current AVL baseline 的幾何差異

## 3.1 Header / reference quantities

| item | old pass `x4.0 exp=1.0` | current `x4.0 exp=1.0` | comment |
| --- | ---: | ---: | --- |
| `IYsym` | `1` | `0` | old 用 global symmetry；current 用 explicit `YDUPLICATE` |
| `Sref` | `30.690000` | `35.175000` | current AVL header 已改成 VSP-calibrated reference |
| `Cref` | `1.005842294` | `1.130174740` | current MAC reference 較大 |
| `Bref` | `33.000000` | `33.000000` | 無變化 |
| `Xref` | `0.251460573` | `0.282543685` | current reference point 向後移約 `31.08 mm` |
| force-file surface count | `3` | `5` | current Wing / Elevator 透過 `YDUPLICATE` 顯式鏡射 |

## 3.2 Wing geometry

| item | old pass | current `exp=1.0` | comment |
| --- | --- | --- | --- |
| section count | `7` | `6` | old 有 `y=1.5 m` station；current 改成 VSP-derived 6-station schedule |
| root chord | `1.39` | `1.30` | 變小 |
| tip chord | `0.47` | `0.435` | 變小 |
| airfoil family | all `NACA 2412` | inboard / root `fx76mp140.dat`, tip `clarkysm.dat` | current 已不是全翼 `2412`，而且 current reference `.vsp3` 是 root FX / tip Clark Y |

### 3.2.1 Wing section `Z` 差異

同樣都是 `x4.0 / exp=1.0`，current wing 在所有共用 outboard station 都比舊案更平：

| `y` station [m] | old `Z` [m] | current `Z` [m] | delta [m] | delta [% vs old] |
| ---: | ---: | ---: | ---: | ---: |
| `4.5` | `0.21818` | `0.14280` | `-0.07538` | `-34.5%` |
| `7.5` | `0.89818` | `0.43326` | `-0.46493` | `-51.8%` |
| `10.5` | `2.24000` | `0.99068` | `-1.24932` | `-55.8%` |
| `13.5` | `4.52545` | `1.90121` | `-2.62425` | `-58.0%` |
| `16.5` | `6.92000` | `3.25122` | `-3.66878` | `-53.0%` |

這說明 old pass case 與 current baseline 的 wing shape 確實不是同一套。

## 3.3 Tail / fin geometry

| item | old pass | current | comment |
| --- | ---: | ---: | --- |
| horizontal tail `x` | `4.0` | `6.5` | current HT 往後移 |
| horizontal tail half-span | `1.5` | `2.0` | current HT 變大 |
| horizontal tail chord | `0.8` | `0.9` | current HT 變大 |
| fin `x` | `5.0` | `7.0` | current fin 往後移 |
| fin section `z` | `[-0.7, +1.7]` | `[-0.7, +1.7]` | 相同 |

## 4. `Sref / Cref / Bref / Xref / CG / tail / fin / wing section Z` 哪些有變？

### 4.1 有變的

- `Sref`
  - old: `30.69`
  - current AVL header: `35.175`
- `Cref`
  - old: `1.005842294`
  - current: `1.130174740`
- `Xref`
  - old: `0.251460573`
  - current: `0.282543685`
- `tail`
  - HT 從 `x=4.0, half-span=1.5, chord=0.8`
  - 變成 `x=6.5, half-span=2.0, chord=0.9`
- `fin`
  - 從 `x=5.0`
  - 變成 `x=7.0`
- `wing section Z`
  - current 在相同 `x4.0 exp=1.0` 下明顯更平

### 4.2 沒變的

- `Bref`
  - 都是 `33.0`
- fin 的 section `z` 範圍
  - 都是 `-0.7` 到 `+1.7`

### 4.3 `CG` 要分成兩層看

這裡不能只看 metadata，因為 **metadata 裡的 mode-parameter CG 和實際 trim run 用到的 `X_cg` 不是同一件事**。

| item | old | current | comment |
| --- | ---: | ---: | --- |
| metadata `x_cg` | `0.251460573` | `0.234843900` | 這是 `estimate_mode_parameters()` 算出的預設 mode CG |
| actual trim log `X_cg` | `0.2515` | `0.2825` | 這次 trim run 沒有 `MASS` 套進去；實際 `.OPER` 顯示的是 `Xref` |

所以若你問「這次 trim run 實際 reference / CG 有沒有變」，答案是：

- **有，而且這次真正在用的是 `Xref`，不是 metadata 的 `0.23484`。**

## 5. `cl_required` 為什麼從約 `1.2352` 變成約 `1.3242`？

## 5.1 直接原因

因為 campaign 不是拿 AVL case header 的 `Sref` 算，而是拿這個 proxy：

```text
estimate_reference_area(cfg) = 0.5 * span * (root_chord + tip_chord)
```

### old pass case 對應的 proxy area

- old root / tip chord：`1.39 / 0.47`
- `0.5 * 33 * (1.39 + 0.47) = 30.69`
- 這剛好和 old AVL header `Sref = 30.69` 一致
- 所以 old campaign 的 `cl_required` 沒有 reference mismatch

### current repaired path 對應的 proxy area

- current root / tip chord：`1.30 / 0.435`
- `0.5 * 33 * (1.30 + 0.435) = 28.6275`
- campaign 就是用這個 `28.6275` 去算：

```text
cl_required = W / (q * S_proxy)
            = 981 / (0.5 * 1.225 * 6.5^2 * 28.6275)
            = 1.324197543
```

### 但 current AVL header 實際是什麼？

- current `case.avl` / `case_trim.ft` 寫的是：
  - `Sref = 35.175`
  - `Cref = 1.1302`
  - `Bref = 33.0`

若用 **同一份 current AVL case header 的 `Sref=35.175`** 來算，則：

```text
cl_required_consistent = 981 / (0.5 * 1.225 * 6.5^2 * 35.175)
                       = 1.077710452
```

也就是說：

- old：`30.69` proxy area 和 old AVL header 一致
- current：`28.6275` proxy area 和 current AVL header `35.175` **不一致**

**這就是 `1.2352 -> 1.3242` 的主因。**

## 5.2 這不是 `Sref` 變大導致 `CL` 變大，而是 gate 根本沒在用 current `Sref`

如果只看 current AVL header，你會直覺覺得：

- `Sref` 從 `30.69` 變成 `35.175`
- required CL 應該下降才對

這個直覺沒有錯。

問題在於 repaired campaign 的 gate 沒有採用這個 `35.175`，而是沿用 root/tip trapezoid proxy area `28.6275`。
所以表面上看起來像「`Sref` 變大但 `cl_required` 也變大」，其實是 **兩個不同 reference-area contract 被混用**。

## 6. trim AoA 為什麼從約 `11.568 deg` 變成約 `12.528 deg`？

## 6.1 先看三個對照點

| case | CL target | trim AoA [deg] | note |
| --- | ---: | ---: | --- |
| old pass `x4.0 exp=1.0` | `1.2352058` | `11.56845` | archive artifact |
| current `x4.0 exp=1.0`, but forced to old CL | `1.2352058` | `11.67279` | 這次最小必要 direct AVL 驗證 |
| current repaired gate `x4.0 exp=1.0` | `1.3241975` | `12.52845` | Track Z full-gate artifact |

## 6.2 這代表什麼

把 current geometry 本身的影響先抽出來看：

- old `11.56845`
- current geometry at old CL `11.67279`
- 幾何 / aero baseline 本身只多了：
  - `+0.10434 deg`

再看 current gate 額外加上去的量：

- current geometry at old CL `11.67279`
- current repaired gate `12.52845`
- reference-area mismatch 額外多了：
  - `+0.85566 deg`

總共：

- `12.52845 - 11.56845 = +0.96 deg`

占比約：

- geometry / aero baseline 本身：`10.9%`
- gate reference-area mismatch：`89.1%`

## 6.3 exponent 不是主因

同一套 current baseline 下：

- `x4.0 / exp=1.0` trim AoA：`12.52845`
- `x4.0 / exp=2.2` trim AoA：`12.53560`

只差：

- `+0.00715 deg`

所以這次 old-vs-current regression 的大頭 **不是 exponent**。
`exp=2.2` 會再稍微更差一點，但它只是小尾巴，不是主因。

## 6.4 若 current gate 改成和 current AVL header 一致，AoA 其實會回到 gate 內

我另外直接對 current `x4.0 / exp=1.0` case 做最小必要 AVL 驗證：

- 令 `CL = 1.077710452`（也就是用 current header `Sref=35.175` 算出的 consistent target）
- AVL 回傳：
  - `Alpha = 10.16612 deg`

也就是說：

- **current 幾何 baseline 本身不是必然會卡 trim gate**
- 真正把它推到 `12.528 deg` 的，是 current campaign 使用了偏小的 proxy area 去要求過高的 `CL`

## 7. 這些差異是合理校正，還是把舊可行設計空間洗掉了？

## 7.1 哪些差異屬於合理校正

以下這些我認為大方向上是合理的 baseline 校正：

- 用 VSP-calibrated multi-station wing 取代舊的簡化全翼 `2412` / 舊 chord schedule
- 把 `Sref / Cref / Xref` 對齊到 current reference `.vsp3`
- 把 HT / fin 位置與尺寸對齊到 current config truth
- 用 current baseline 重新做 repaired AVL-first / shortlist / rerun handoff

這些都比較像「把 baseline 往 current production truth 收斂」。

## 7.2 哪個差異是不合理 drift

**不合理的不是 current 幾何校正本身，而是：**

- AVL screening case 已經換成 current VSP-calibrated geometry
- 但 gate `cl_required` 還在吃 old-style trapezoid proxy area

這會造成：

- geometry truth 用一套
- trim gate 用另一套

結果就是：

- 舊 `x4.0 exp=1.0` 這種本來可行、甚至在 current geometry 下也接近可行的設計
- 被一個 reference mismatch 人工推進 `trim_aoa_exceeds_limit`

所以我的判斷是：

- **合理校正有**
- **但目前這個 regression 確實把舊的可行設計空間「不合理地洗掉了一部分」**
- 洗掉它的主因不是 current 幾何 truth，而是 gate contract drift

## 8. 下一步該選哪個方向？

## 8.1 不建議：直接回退 AVL baseline

我不建議把 current AVL baseline 整份退回 old `30.69 / 1.0058 / all-2412 / HT@4.0 / Fin@5.0`。

原因：

- 這會把已經對齊 current VSP/config truth 的基準一起退掉
- 退回去雖然能讓 old pass case 看起來「恢復」，但本質上是在回退主資料，而不是修正 regression 根因

## 8.2 也不建議：保留 current baseline 但只是被動更新 shortlist / gate 解讀

如果 current `1.3242` 這個 gate CL 繼續保留，只靠：

- 更新 shortlist
- 或說「trim gate 現在就是比較嚴」

那其實是在把一個 reference mismatch 正當化。

這樣會讓 repaired AVL-first 持續低估 current baseline 幾何的可用空間。

## 8.3 建議：第三種折衷修正

**我建議第三種做法：**

- **保留 current VSP-calibrated AVL baseline geometry**
  - `Sref=35.175`
  - current tail / fin / wing section schedule
- **但把 repaired campaign 的 `cl_required` reference area 改成和 screening geometry 同一套來源**
  - 至少要和 current AVL header `Sref` 一致
  - 更穩妥的是讓 gate area 和 actual generated screening geometry 共用同一份 source of truth
- **修完後再重建 `exp=1.0` shortlist / gate 判讀**

我認為這才是對這次 forensic 最合理的回應。

## 8.4 若只看這次 forensic，我的 go / no-go 判斷

- 回退 AVL baseline：**No**
- 保留 current baseline 但接受目前 `1.3242` gate 結果：**No**
- 保留 current baseline，修正 gate reference-area contract，再重跑 shortlist：**Yes**

## 9. 最小必要驗證、風險、未完成處

## 9.1 最小必要驗證

這次沒有改 code，只做了最小必要 forensic 驗證：

- 讀 old / current `case.avl`
- 讀 old / current `case_trim.ft` 與 `avl_trim_stdout.log`
- 讀 `case_metadata.json` 與 Track Z / Track X 報告
- 讀 `scripts/dihedral_sweep_campaign.py` 確認 `cl_required` 公式
- 額外做了 `2` 個 one-off AVL 檢查：
  - current `x4.0 exp=1.0` at old `CL=1.235205773`
    - `Alpha = 11.67279 deg`
  - current `x4.0 exp=1.0` at current-header-consistent `CL=1.077710452`
    - `Alpha = 10.16612 deg`

## 9.2 風險

- 我沒有在這次任務裡重跑整包 repaired campaign，所以：
  - 修正 gate area 後，shortlist 的完整排序還沒有重新驗證
  - beta / spiral / structural follow-on 是否完全不變，還需要下一輪 bounded rerun 確認
- `CG` 這塊在 metadata 與 trim log 間有雙軌現象：
  - metadata `x_cg = 0.23484`
  - trim log `X_cg = 0.2825`
  - 這次已足夠說明 trim reference 目前並不乾淨一致，但我沒有在這輪再往更深的 mode / mass-file contract 挖

## 9.3 未完成處

- 還沒把 repaired campaign 改成 geometry-consistent gate area
- 還沒重跑 corrected `exp=1.0` shortlist
- 還沒回答「修正 gate area 後 `x3.5 / x3.75 / x3.875 / x4.0` 的新 ranking 是否維持 Track Z 結論」

## 10. 最後一句

這次 regression forensic 的核心結論是：

- **old pass space 沒有主要被 current geometry 校正洗掉**
- **它主要是被一個 `reference area` contract mismatch 洗掉的**
- 所以下一步應該是 **保留 current baseline，修 gate reference-area contract，再重建 shortlist**，而不是直接把 AVL baseline 整份退回舊版
