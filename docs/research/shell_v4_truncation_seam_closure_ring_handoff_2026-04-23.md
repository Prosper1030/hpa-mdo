# shell_v4 truncation seam closure ring handoff (2026-04-23)

## 這輪已確認的核心結論

- 問題不能再被當成單一 `353` 壞面修補。
- `353/383/410/427/471` 應該被視為同一類幾何物件:
  `truncation seam required closure ring faces`
- 目前的正確工程目標是:
  修這整個 closure-ring face family 的生成規則，而不是逐張面打補丁。

## 目前對 family 的定義

這一類 face 目前可用以下規則辨識:

1. 位在 `connector_band_start_y_m` 附近，也就是 truncation seam 的 connector-side 帶狀區。
2. 來自最後一排仍保留在 inboard BL volume 的 source surface。
3. 在 extBL group 內，它是 source-surface 邊界曲線所對應的 lateral side face。
4. 若某條 side-curve 在 closure-source groups 中只出現一次，代表它是 outer boundary candidate。
5. 其中又同時屬於 connector-band boundary curves 的 outer boundary candidate，才算 required closure ring family。
6. `count > 1` 的 side-curve 對應面屬於 transition cleanup faces，不是這個 family。
7. 不屬於 connector-band boundary 的 `count == 1` 面，屬於 retained outer interface，不是這個 family。
8. BL top sheet 也不屬於這個 family。

換句話說，這個 family 不是用單一 tag 定義，而是用
`closure-source patch + unique outer side curve + connector-band ownership`
這個拓撲關係定義。

## 這輪已經做對的事

### 1. 已從 single-face patch 轉成 class-level rebuild

- 現在 closure block 的辨識邏輯已經不是 `if face == 353` 這種特判。
- helper path 上，`353/383/410/427/471` 已經會被一起辨識為同一個 closure-ring family。
- 測試
  `test_real_main_wing_tip_truncation_closure_block_rebuilds_single_local_volume_and_drops_transition_surfaces`
  已通過。

### 2. 已確認不要再走舊的 extBL side-face 碎面幾何

- 舊策略如果直接沿用 extBL 生成的 side-face 幾何，容易把 closure ring 當成自動碎面去沿用。
- 這不符合這個 family 的工程需求。
- 現在方向已改成:
  用 boundary curves 顯式重建 closure ring faces。

### 3. 已確認不能在 BL extrusion 後再補跑一次 `mesh.generate(2)`

- 在實際 real-wing route 裡，BL extrusion 後額外再跑 `gmsh.model.mesh.generate(2)` 會破壞 root-side closure contract。
- 這不是小副作用，而是會把原本還活著的 root-side faces 搞掉。
- 所以這條 closure-ring 修法必須建立在
  `不靠 post-extrusion mesh.generate(2) 重新抽幾何`
  的前提上。

## 目前真正遇到的問題

### 問題 A: real prelaunch 還沒有 clean

目前 `test_run_shell_v4_real_main_wing_prelaunch_smoke_reaches_prelaunch_clean_with_tip_truncation`
仍然失敗。

這表示:

- helper-family 的 class-level rebuild 已經站住了。
- 但 real-wing end-to-end 還沒有真正打通。

### 問題 B: 現在的第一個失敗已經不是舊的 legacy family

這點很重要。

早期失敗是舊的 legacy closure face 自己爆掉，例如:

- `353` 先死
- 修完 `353` 以後，`383` 可能用同型態立刻接著死

這代表規則不夠通用。

但現在這輪不是這個狀況。

現在 real prelaunch 的第一個 failure 已經換成:

- rebuilt closure surfaces `376/377/378`
- 在 global remesh / edge recovery 階段出現
  `The 1D mesh seems not to be forming a closed loop`
- 同時伴隨
  `No elements in surface 376 377 378`
  和多個 `Unable to recover edge ... on curve ...` warning

所以現在的 failure family 已經不是原本的
`legacy required closure ring faces`
本體，而是下一層的
`rebuilt closure-strip remesh / edge-recovery contract`
問題。

### 問題 C: full real route 跟簡化 probe 的 surface behavior 不一樣

這輪一開始很容易被誤導的點是:

- 簡化 probe 下，某些 closure ring surface 只看到 1 個 outer interior point。
- 但正式 `run_shell_v4_half_wing_bl_mesh_macsafe` 路徑會先套 transfinite controls。
- 在 full route 下，rebuild detail 顯示 `376/377` 的 outer trace 其實是高密度的 22-point interior trace。

也就是說:

- 簡化 probe 只能證明「方向大致合理」。
- 但不能直接當成正式 prelaunch 的幾何真相。

### 問題 D: 目前 rebuilt outer trace 的 ordering 還不夠可靠

現在的 `explicit_boundary_curve_plane_strip` 路線，已經把問題縮到很清楚:

- connector-side curve 是可信的
- family 辨識也是可信的
- 但 full route 下 reconstructed outer trace 的 ordering 仍可能不對
- ordering 一旦錯，重建出來的 plane strip 會在 1D mesh recovery 時出現自交或非閉合 loop

工程上看，這不是「還有某張壞面沒修」，
而是「rebuild 後的 closure-strip 邊界曲線順序還不夠物理一致」。

## 目前想解決的東西

### 1. 讓 outer trace ordering 變成 deterministic topology ordering

目前最想解掉的，不是再去改 `353` 或某個 surface tag，
而是把 rebuilt closure strip 的 outer boundary ordering 做成真正可靠的規則。

理想做法:

- 不要再用 heuristic / greedy 最近點排序當最終答案。
- 改成從可驗證的拓撲順序還原 outer trace。
- 讓 connector-side endpoint 到 outboard closure endpoint 的 path 有唯一、一致、可重現的順序。

### 2. 讓 rebuilt closure strip 在 full prelaunch 的 global remesh 下穩定

目標不是只有建出 surface，而是要讓它在下面這串流程都穩定:

1. full route with transfinite controls
2. BL protection field active
3. closure-block rebuild
4. global `mesh.generate(2)`
5. edge recovery
6. `mesh.generate(3)`

只有這整串都能過，才算真的修好。

### 3. 讓 failure 不再卡在 rebuilt surfaces `376/377/378`

如果下次 real prelaunch 再失敗，理想情況應該是:

- 不再死在 closure-ring rebuild 這一層
- 而是進到真正後續的 volume / quality / solver-validation 問題

如果還是 `376/377/378` 在全域 remesh 掛掉，
就代表 closure-strip ordering / curve construction 還沒收斂。

## 目前的 go / no-go 判斷

### 可以算已完成的部分

- 已把 `353/383/410/427/471` 視為同一類 face family。
- 已從單面修補轉成 class-level rebuild。
- 已確認不能依賴單一 tag 特判。

### 還不能算完成的部分

- `real-wing prelaunch` 還沒有 finally clean。
- 現在卡住的已經不是舊 family，而是 rebuilt closure-strip surfaces 的 remesh / edge-recovery family。

## 一句話總結

這輪不是沒進展，而是已經把問題從
`353 special-case patch`
成功往前推成
`closure-ring family rebuild`
再往後推到
`rebuilt closure-strip ordering / remesh contract`
這個新的、更本質的 blocker。

現在真正要解的最後一層，不是再修某張面，
而是把 full route 下 rebuilt closure strip 的 boundary ordering 與 edge-recovery contract 做穩。
