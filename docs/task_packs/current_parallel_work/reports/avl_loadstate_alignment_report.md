# Track W — AVL / Legacy / Rerun Load-State Alignment Compare

> 文件性質：Track W 最小必要對比報告
> 任務日期：2026-04-19
> 任務目標：比較 `legacy_refresh`、repaired `candidate_avl_spanwise`、`candidate_rerun_vspaero` 在同一組 seed 下的 AoA / load-state / structural outcome，判斷 repaired AVL path 現在能不能被描述成「舊 AVL-first flow + candidate-owned spanwise lift distribution」。

## 1. 先講結論

- 以這次最小必要 compare 來看，**還不能**把 repaired `candidate_avl_spanwise` 描述成：
  - `舊 AVL-first 外圈 + candidate-owned spanwise lift distribution`
- Track V 修掉的是 **ownership / gate / recovery drift**，這部分仍然成立。
- 但在這組共同 seed 上，repaired `candidate_avl_spanwise` 的 **實際 selected AoA / load-state 數值** 還是沒有和 `legacy_refresh` / `candidate_rerun_vspaero` 對齊。
- 關鍵差異不是只有「同一工況下換成更細的 spanwise lift distribution」：
  - `legacy_refresh`：`selected_cruise_aoa_deg = 0.000`
  - repaired `candidate_avl_spanwise`：`selected_cruise_aoa_deg = 12.536`
  - `candidate_rerun_vspaero`：`selected_cruise_aoa_deg = 4.000`
- 展向總載荷量級也顯示 repaired AVL 目前更像是**另一個 candidate state**，不是 confirm-level 的小差異：
  - `legacy_refresh`：`total half-span lift = 450.904 N`，`total |torque| half-span = 260.296 N*m`
  - repaired `candidate_avl_spanwise`：`570.711 N`，`0.623 N*m`
  - `candidate_rerun_vspaero`：`448.190 N`，`228.141 N*m`
- 所以這包的結論是：
  - **semantic ownership 已修回來**
  - **numeric load-state alignment 還沒修乾淨**
  - **現在不建議直接進 Track X**

## 2. 比較設定

### 2.1 共同 seed

- `target_shape_z_scale = 4.0`
- `dihedral_exponent = 2.2`
- `rib_zonewise = off`

固定 structural seed 沿用 Track V 報告：

- `main_plateau_grid = 1.0`
- `main_taper_fill_grid = 0.999999500019976`
- `rear_radius_grid = 0.9999997444012075`
- `rear_outboard_grid = 1.0`
- `wall_thickness_grid = 0.04630959736295326`

### 2.2 這次實際使用的資料來源

- `legacy_refresh`
  - 重用 Track V 已驗證 direct compare output：
  - `/tmp/track_v_direct_legacy/direct_dual_beam_inverse_design_refresh_summary.json`
- repaired `candidate_avl_spanwise`
  - 重用 Track V 已驗證 direct compare output：
  - `/tmp/track_v_direct_candidate_avl/direct_dual_beam_inverse_design_refresh_summary.json`
- `candidate_rerun_vspaero`
  - 本次重新執行 direct compare：
  - `/tmp/track_w_direct_candidate_rerun_nolocal/direct_dual_beam_inverse_design_refresh_summary.json`
  - 這次額外加上 `--skip-local-refine`，避免 rerun path 自己往更輕的解滑過去，讓主 compare 保持 fixed-seed apples-to-apples

### 2.3 `skip-aero-gates` 說明

- `legacy_refresh`
  - 這份 direct compare 本身**沒有**用 `--skip-aero-gates`
- repaired `candidate_avl_spanwise`
  - 這份 direct compare 本身**沒有**用 `--skip-aero-gates`
  - 但它吃的 `candidate_avl_spanwise_loads.json` 仍然是 Track V 的 debug bootstrap artifact：
    - `/tmp/track_v_smoke_candidate_debug/mult_4p000/candidate_avl_spanwise/candidate_avl_spanwise_loads.json`
  - Track V 已經證明 full-gate smoke 下它不會偷跑結構路徑；只是這組 seed 在 full-gate compare 下不會留下可拿來做 direct structural compare 的 candidate AVL artifact，所以目前仍要借 debug bootstrap
- `candidate_rerun_vspaero`
  - 這次 direct compare **沒有**用 `--skip-aero-gates`

## 3. Side-by-Side Compare

主表使用：

- 同一組 seed
- 同樣 `2` 步 refresh
- `candidate_rerun_vspaero` 關掉 local refine

| path | `selected_cruise_aoa_deg` | final `load_source` | total structural mass | jig ground clearance | total half-span lift | total `|torque|` half-span | feasible / fail reason | recovery | `skip-aero-gates` |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `legacy_refresh` | `0.000 deg` | `legacy_refresh:legacy_twist_refresh_from_cfg_sweep:step_2_from_iteration_1` | `21.740001 kg` | `-26.532 mm` | `450.904 N` | `260.296 N*m` | `fail: ground_clearance` | `enabled=true`, `triggered=true` | `no` |
| repaired `candidate_avl_spanwise` | `12.536 deg` | `candidate_avl_spanwise:candidate_owned_twist_refresh_from_avl_spanwise_sweep:step_2_from_iteration_1` | `21.740001 kg` | `+33.523 mm` | `570.711 N` | `0.623 N*m` | `pass` | `enabled=true`, `triggered=false` | `compare run no; artifact bootstrap yes` |
| `candidate_rerun_vspaero` | `4.000 deg` | `candidate_rerun_vspaero:candidate_owned_twist_refresh_from_rerun_sweep:step_2_from_iteration_1` | `21.740001 kg` | `+0.621 mm` | `448.190 N` | `228.141 N*m` | `pass` | `enabled=true`, `triggered=false` | `no` |

### 3.1 最重要的數值差異

- repaired `candidate_avl_spanwise` vs `candidate_rerun_vspaero`
  - `AoA`: `+8.536 deg`
  - `lift`: `+122.521 N` (`+27.3%`)
  - `|torque|`: `-227.518 N*m` (`-99.7%`)
  - `clearance`: `+32.902 mm`
- `legacy_refresh` vs `candidate_rerun_vspaero`
  - `AoA`: `-4.000 deg`
  - `lift`: `+2.714 N` (`+0.6%`)
  - `|torque|`: `+32.156 N*m` (`+14.1%`)
  - `clearance`: `-27.153 mm`

### 3.2 這代表什麼

- `legacy_refresh` 和 `candidate_rerun_vspaero` 至少還在**同一個量級、同一種候選狀態附近**
  - lift 很接近
  - torque 有可理解的 confirm-level 差異
  - clearance 都接近地板邊界，只是 legacy 還是負值、rerun 剛好翻正
- repaired `candidate_avl_spanwise` 則不是這種「同一 candidate state 的 confirm-level 差異」
  - 它的 lift 明顯更大
  - 它的 torque 幾乎被洗到接近零
  - clearance 也從 near-boundary 直接變成明顯正值

## 4. 判讀

### 4.1 repaired `candidate_avl_spanwise` 的 AoA / load-state ownership 是否還和舊流程一致？

- **在 code contract / ownership metadata 層面，大致一致。**
- Track V 已經把下面這些 drift 修回來了：
  - 不再強制關閉 recovery
  - 不再把 `candidate_avl_spanwise` 說成新的 AoA owner
  - contract note 也明講 outer-loop AVL trim / gates 才是 owner

但：

- **在這組 seed 的實際數值結果上，還不能說它已經和舊流程對齊。**
- 原因不是 ownership 描述文字不對，而是它目前吃到的 selected AVL state 本身，和 legacy / rerun 對應到的 state 還差很多。

### 4.2 它只是多了 spanwise lift distribution，還是仍然偷偷換了一個新工況？

- 以這次 compare 來看，**不像只是多了 spanwise lift distribution。**
- 比較像是：
  - semantic ownership 已經收回來
  - 但 numeric selected state 仍然落在另一個工況上
- 最直觀的證據就是：
  - `AoA 12.536 deg` 對 `0.000 / 4.000 deg`
  - `lift 570.711 N` 對 `450.904 / 448.190 N`
  - `|torque| 0.623 N*m` 對 `260.296 / 228.141 N*m`

如果只是「同一個已選 candidate state，多了更合理的 spanwise lift distribution」，
那比較合理的預期應該是：

- AoA 差不會這麼大
- total lift / torque 不會跳到另一個量級
- clearance verdict 不會直接從 near-boundary 變成明顯翻正很多

### 4.3 它和 `candidate_rerun_vspaero` 的差異，是 confirm-level 差異，還是已經大到像另一個完全不同的 candidate state？

- **已經大到比較像另一個 candidate state。**
- `legacy_refresh` 和 `candidate_rerun_vspaero` 之間，還比較像 confirm-level 差異。
- repaired `candidate_avl_spanwise` 和 `candidate_rerun_vspaero` 之間，則不是。

## 5. 額外觀察：path-level rerun 會再往更輕的解滑

如果把 `candidate_rerun_vspaero` 的 local refine 打開：

- output:
  - `/tmp/track_w_direct_candidate_rerun/direct_dual_beam_inverse_design_refresh_summary.json`
- final selected mass 會從 fixed-seed compare 的 `21.740001 kg` 再降到 `20.940023 kg`
- 但 final load metrics 仍然大致維持在：
  - `total half-span lift ~= 448.663 N`
  - `total |torque| half-span ~= 228.373 N*m`

所以：

- rerun path 的 local refine 會影響 path-level winner mass
- 但**不會改變這次 Track W 的主判斷**
- 主判斷仍然是 repaired `candidate_avl_spanwise` 的 numeric state 和 rerun 不在同一個 candidate state 上

## 6. 風險與未完成處

- 這次只做了 prompt 要求的最小必要共同 seed，**還沒加**：
  - 一組較接近 clearance pass region 的 seed
  - 一組較保守 seed
- repaired `candidate_avl_spanwise` 的 direct structural compare，仍然仰賴 Track V 的 debug bootstrap artifact
  - 也就是說，這組 seed 上還沒有做到「完全不靠 debug bootstrap、直接從正常 full-gate 流程留下 candidate AVL artifact 再 compare」
- 因此這包可以明確回答「現在還不能直接說 repaired AVL path 已經等於舊流程 + spanwise ownership」，
  但還不能把原因完全縮到單一一行 bug；它更像是：
  - ownership drift 已修
  - selected numeric state 還沒對齊

## 7. 是否直接進 Track X？

- **目前不建議直接進 Track X。**

原因：

- Track X 要用 repaired AVL-first path 重建 shortlist
- 但這次 compare 顯示 repaired `candidate_avl_spanwise` 在關鍵共同 seed 上，還不像是「舊流程 + spanwise distribution」
- 如果現在直接用它重建 shortlist，等於把一個仍然 state-misaligned 的 path 當成正式 shortlist owner

比較穩的下一步應該是先補一個更小的修正或 compare 包，目標至少擇一成立：

1. 讓 repaired `candidate_avl_spanwise` 可以在**不靠 debug bootstrap** 的正常比較路徑下留下可用 artifact
2. 或者在一組 **gate-passing** 的共同 seed 上，證明它的 `selected_cruise_aoa_deg` / lift / torque 真的貼近 rerun，只剩 spanwise-distribution-level 差異

在這之前，直接進 Track X 的風險偏高。
