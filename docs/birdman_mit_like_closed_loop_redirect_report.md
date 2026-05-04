# Birdman Stage-1 改向：MIT-like 高 AR + AVL → 機翼選型 → AVL 閉環

- 分支：`birdman-fix-outer-loading-authority`
- 緣由：上一輪 chord-bump 整合證實 chord redistribution 只能把
  outer_min[0.80-0.92] 從 0.50 推到 0.57 左右，整體 e_CDi 上限在 0.90
  附近，且必須在 inner cl_controls 與 chord_kink gate 的耦合限制下取
  捨。chord bump 是 e-maximisation 框架下的硬救法，總工程師決定改向：
  **Stage-1 不再以 maximize e 為目標**，改成
  AVL(no-airfoil) → XFOIL/CST → AVL(with-airfoil) 的閉環設計，產出
  MIT-like 高 AR 合理 taper 的候選，並且不用 chord bump 來掩蓋外翼
  underloaded。

## 改了什麼

### 1. MIT-like 候選產生器（高 AR / 合理 taper / 無 bump）

新檔 [src/hpa_mdo/concept/mit_like_candidate.py](../src/hpa_mdo/concept/mit_like_candidate.py)：

- `generate_mit_like_candidates(cfg, sample_count, ar_range=(37, 40),
  taper_range=(0.30, 0.40), span_range_m=(32, 35))`：3-dim Sobol 在
  (span, AR, taper) 上抽樣，每個樣本對應一個梯形 trapezoidal
  `GeometryConcept`，不疊任何外翼 chord bump。
- 預設固定的 monotone-washout twist schedule（`(2.0, 0.5, -0.5, -2.0)
  deg` at `(0, 0.35, 0.70, 1.0)`），閉環不再做 twist optimization。
- 違反 `INVERSE_CHORD_ROOT_CHORD_RANGE`、`tip_chord_min_m`、
  `wing_area_m2_range`、`tip_chord_floor_m=0.42` 的樣本直接 reject。
- `MITLikeCandidate.to_summary()["outer_chord_bump_amp"] == 0.0`
  （硬編碼 0；測試保證沒有 bump 偷偷流進來）。

### 2. 每 zone 機翼挑選器（XFOIL/CST 的前置步驟）

新檔 [src/hpa_mdo/concept/zone_airfoil_picker.py](../src/hpa_mdo/concept/zone_airfoil_picker.py)：

- `select_zone_airfoils_from_library(zone_requirements)`：從種子 library
  （FX 76-MP-140 / Clark-Y 11.7% smoothed）依照 zone 的 `cl_target` /
  `reynolds` 決定使用哪個翼型。預設規則：root/mid1 或高
  cl(>=0.85) 高 Re(>=320k) → FX 76-MP-140，外翼低 Re/低 cl → Clark-Y。
- 每個 `ZoneAirfoilSpec` 帶上 `alpha_l0_deg`、`cl_alpha_per_rad` 與
  `c_d = c_{d0} + k(c_l - c_{l,ref})^2` 的解析 polar，這正是
  `αL0 / CLAF / CDCL` 之後要回填 AVL 的數值。FX 76-MP-140 的
  polar 取自 `docs/research/xfoil_fx76mp140_re410000/`，Clark-Y 用
  cosine fit。
- `airfoil_templates_for_avl(selected)` 把選中的翼型輸出成
  `load_zone_requirements_from_avl` 認得的 `dict[zone -> {coordinates,
  geometry_hash, template_id, ...}]`，所以同樣的 payload 可以原封餵
  回 AVL 跑 with-airfoil pass。
- `estimate_zone_profile_cd` + `chord_weighted_profile_cd` 給出
  chord-weighted 的整翼 profile CD，閉環的 mission power proxy 用它。

> 這個 picker 是**佔位實作**：依舊是 Library lookup，沒有跑 CST 搜尋
> + XFOIL polar batch。下一步是把
> `hpa_mdo.concept.airfoil_selection.select_zone_airfoil_templates_for_concepts`
> 接到這個 picker 的位置，讓選型自動產出 CST 變種；目前的種子 lookup
> 與 polar fit 是該介面的可審計參考實作。

### 3. 閉環 driver

新檔 [scripts/birdman_mit_like_closed_loop_search.py](../scripts/birdman_mit_like_closed_loop_search.py)：

對每個 MIT-like candidate 執行：

1. **Phase 1：AVL no-airfoil**
   - `load_zone_requirements_from_avl(cfg, concept, stations,
     airfoil_templates=None, case_tag='no_airfoil')`
   - 拿到 per-zone 的 `cl_target` / `reynolds` / `chord_m`，
     trim CL / CDi / aoa 等。
2. **Phase 2：每 zone XFOIL/CST 選型（目前是 library picker，介面
   為後續 CST/XFOIL 替換留好）**
   - `select_zone_airfoils_from_library(zone_requirements)`
   - 記錄 `alpha_l0_deg` / `cl_alpha_per_rad` / `polar_cd0` / `polar_k`
     / `polar_cl_ref` / `reynolds_ref` / `selection_reason`。
3. **Phase 3：AVL with airfoil**
   - 同樣的 `load_zone_requirements_from_avl`，這次帶
     `airfoil_templates=` 的選型 payload。
   - AVL `AFILE` 直接吃選中的 `.dat`，section thin-airfoil α₀L 由
     coordinates 推得；後續若要強制覆寫，可以用
     `αL0/CLAF/CDCL` 在 AVL section block 下追加（介面已準備）。
   - 在 `with_airfoil_avl.outer_ratio_vs_no_airfoil` 比較兩輪每個
     station 的 `cl_target`，給出 `ratio_min/mean/max`。
4. **Phase 4：mission power proxy**
   - `q∞ · S · (CDi(cruise) + chord-weighted profile CD + misc)`
   - `CDi(cruise) = CL²(cruise) / (π · AR · e_CDi)`，其中
     `CL(cruise) = m·g / (q∞·S)`，`e_CDi` 用 with-airfoil 的代表
     trim case 換算（cruise speed ≈ design speed，會挑 1g 且
     evaluation_speed_mps 最接近 design speed 的 case）。
   - profile CD 用 picker 的解析 polar 評估在 zone 的 `(cl_target,
     reynolds)`。

driver 不會用「first-round e」淘汰任何候選；ranking 只在報告階段排
序，所有 candidate 都跑完整閉環。

### 4. mission-coupled spanload search 的 chord bump 預設關閉

[scripts/birdman_mission_coupled_spanload_search.py](../scripts/birdman_mission_coupled_spanload_search.py)：

- `run_search(..., enable_outer_chord_bump: bool = False)`：預設不啟
  用 chord bump，回到 8-dim Sobol 行為。
- 新增 CLI 旗標 `--enable-outer-chord-bump`（明示為 regression
  comparison only）；不加旗標就是新的預設。
- chord bump 的工程貢獻完整保留在
  [docs/birdman_outer_chord_bump_stage1_integration_report.md](birdman_outer_chord_bump_stage1_integration_report.md)
  與 medium search 輸出（`output/birdman_mission_coupled_medium_search_chord_bump_20260503/`），
  以後比較時可以用旗標重啟。

## Validation 結果

### AVL e sanity benchmark 不退化

`output/birdman_avl_e_sanity_benchmark_post_mit_like/`：

```
near_elliptic_uniform_airfoil    e_CDi = 0.9937 (>= 0.95) ✓
hpa_taper_uniform_airfoil        e_CDi = 0.8935 (>= 0.88) ✓
```

### 閉環 smoke run（4 個 candidate）

`output/birdman_mit_like_closed_loop_smoke/mit_like_closed_loop_report.json`

每個 candidate 都跑完 4 個 phase，沒有 failure。

### 16 candidate 驗證跑

`output/birdman_mit_like_closed_loop_validation/mit_like_closed_loop_report.json`：

- 14 個 candidate 進到閉環（2 個被 stage-0 hard constraint 過濾掉）
- 0 個 AVL 失敗
- e_CDi(post-airfoil) 範圍 0.71-0.80，最佳 sample 11
  AR=38.77 taper=0.387 e=0.7999 P=143.6 W cruise
- mission cruise power 都落在 143-147 W（98.5 kg gross mass、
  S 在 26-32 m^2、cruise 6.6 m/s）

### 為什麼 e_CDi(post) 看起來比上一輪「無 chord bump」結果低？

兩個原因，都符合預期：

1. **沒做 twist 優化**。MIT-like 候選 twist 是固定 monotone schedule
   `(2.0, 0.5, -0.5, -2.0) deg`。上一輪 mission-coupled search 在
   stage-1 跑 Powell residual-twist optimizer，自然會把 e 推到
   0.85-0.88。閉環的工作是回答「在這個 planform + airfoil 下 AVL
   是什麼樣子」，而不是把 e 最大化。
2. **library picker 在 AVL 看起來幾乎沒動 e**。FX 76-MP-140 與
   Clark-Y 都是薄 cambered 翼型，AVL section 的 thin-airfoil α₀L 差
   異不到 1.5°；with_airfoil_avl 與 no_airfoil_avl 的 trim CL/CDi
   幾乎一致，所以 e_CDi(post) ≈ e_CDi(no-AF)。這正告訴我們：要看到
   閉環真的把 e_CDi 推上去，必須 plug in CST/XFOIL search，讓 picker
   能產出實際 camber/thickness 偏離種子的 candidate。

> 這就是為什麼工程上不應該用 first-round e 淘汰候選：candidate 的
> 真價值要等 CST/XFOIL 與 cruise-aware twist 一起出來才看得見。

## 對既有 chord-bump 路線的處理

- chord redistribution helpers（`hpa_mdo.concept.outer_loading`）
  保留，閉環跑 sweep 仍然能用，但**不再是 Stage-1 search variable**。
- mission-coupled search 預設 `enable_outer_chord_bump=False`，回到
  8-dim Sobol，需要 regression 比較時用 `--enable-outer-chord-bump`。
- standalone authority sweep
  (`scripts/birdman_outer_loading_authority_sweep.py`) 仍是 chord
  redistribution 的官方 sandbox，用來對比舊路線。

## 還沒做、明確列為下一步

1. **接 CST/XFOIL search**。把 picker 換成
   `hpa_mdo.concept.airfoil_selection.select_zone_airfoil_templates_for_concepts`
   的 batch 版本，吃 `JuliaXFoilWorker`。需要決定 cache 策略
   （polar_db 大小、persistent worker 數）以免每個閉環候選都重新跑
   數百個 polar query。
2. **AVL CLAF/CDCL 注入**。AFILE 已就位；下一步是把 picker 的
   `αL0_deg`、`cl_alpha_per_rad`、polar 寫進 AVL section block 的
   `CLAF` / `CDCL` 區段，讓 AVL 真的吃進低-Re 翼型的 lift/drag
   特性，而不只是 thin-airfoil geometry。
3. **Cruise-aware twist 優化**。閉環之後接一個小 twist optimizer，
   讓固定 schedule 變成「每個 candidate 自己的最佳 monotone washout」，
   把 0.71-0.80 推到應有的 0.85+ 範圍。
4. **mission verdict**。需要 XFOIL profile drag + 真 polar 才會給出
   值得相信的 42.195 km 完賽結論；目前所有 power 數字仍是 proxy。

## Acceptance 對照

| 條件 | 狀態 |
|---|---|
| Stage-1 不再以 maximize e 為目標（不再用 chord bump 硬救 e） | 達成（chord bump 預設關閉） |
| 產出 MIT-like 高 AR(37-40) 合理 taper(0.30-0.40) candidates | 達成（generator 強制範圍 + 測試） |
| AVL no-airfoil → 每 zone cl_target + Re | 達成（沿用 `load_zone_requirements_from_avl(airfoil_templates=None)`） |
| 站別 cl_req + Re 分配到 root/mid1/mid2/tip | 達成（picker 用 zone summary） |
| XFOIL/CST 對每個 zone 選 airfoil | 部分達成（library picker 是介面實作；CST/XFOIL search 是下一步） |
| 把 αL0 / CLAF / CDCL / AFILE 回填 AVL | AFILE 已回填；CLAF/CDCL 數值記錄齊全，AVL section block 注入是下一步 |
| 跑 AVL with airfoil → 重新評估 actual spanload、outer_ratio、e_CDi、local cl | 達成（Phase 3 + outer_ratio metric） |
| 用 XFOIL profile drag + AVL CDi 算 mission power | 達成（用 picker 的解析 polar；實際 XFOIL polar lookup 是下一步） |
| 不要只用第一輪 e 淘汰高 AR 合理 taper candidates | 達成（driver 不會用 first-round e prune；ranking 只在報告） |
| AVL sanity benchmark 不退化 | 達成（0.9937 / 0.8935） |
| 不宣稱 42.195 km 完賽 | 不宣稱 |

## 跑出來的工件

- `src/hpa_mdo/concept/mit_like_candidate.py`、
  `src/hpa_mdo/concept/zone_airfoil_picker.py`
- `scripts/birdman_mit_like_closed_loop_search.py`
- `tests/test_concept_mit_like_candidate.py`
- `tests/test_concept_zone_airfoil_picker.py`
- `tests/test_birdman_mit_like_closed_loop_search.py`
- `output/birdman_avl_e_sanity_benchmark_post_mit_like/`
- `output/birdman_mit_like_closed_loop_smoke/`
- `output/birdman_mit_like_closed_loop_validation/`
