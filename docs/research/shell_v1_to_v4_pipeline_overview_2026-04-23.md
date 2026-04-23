# shell_v1 到 shell_v4 pipeline 高角度總整理 (2026-04-23)

## 先講清楚這份文件的 scope

這份整理講的是 `shell_v1 ~ shell_v4` 這條
`ESP rebuilt main-wing / shell` 演化線，
不是 `hpa_meshing_package` README 裡寫的 formal package `v1` product line。

也就是說：

- formal package `v1`:
  `openvsp_surface_intersection -> thin_sheet_aircraft_assembly -> mesh_handoff.v1 -> su2_handoff.v1`
- 這份文件在講的 `shell_v1 ~ shell_v4`:
  真實主翼 / `esp_rebuilt` / tip-end topology / near-wall / BL / solver-validation 這條 experimental-to-mainline 學習線

如果把兩者混在一起看，會很容易誤判現在 pipeline 到底成熟到哪一層。

## 一句話總結整條線

`shell_v1 -> shell_v4` 不是四個彼此獨立的方案，
而是同一條 pipeline 不斷把 blocker 往後推的過程：

1. `v1` 先讓東西「能出 3D volume smoke」
2. `v2` 把最嚴重的 tip sliver / ill-shaped tet 壓下去，做出可比較的 control baseline
3. `v3` 把根因從 downstream patch 往 upstream seam topology 推，最後得到可凍結的 geometry baseline
4. `v4` 承認 `v3` 那條 tetra shell 線不適合再硬塞 boundary layer，改開新的 half-wing BL / solver-validation 路線

所以高角度來看，這條 pipeline 的核心不是「一直修 bug」，
而是每一代都在回答一個更清楚的工程問題：

- 問題是幾何嗎？
- 是 local meshing policy 嗎？
- 是 near-wall route 本身不對嗎？
- 還是已經進到 solver-entry / 3D volume-side contract 了？

## 先給結論

### 這四代各自真正完成了什麼

| 代別 | 真正完成的事 | 沒完成的事 |
| --- | --- | --- |
| `shell_v1` | 讓 `esp_rebuilt main_wing` 走到第一批可完成的 3D smoke | tip-end sliver family 很重，品質還差 |
| `shell_v2` | 把 tip sliver 問題從「大量 ill-shaped tet」壓到「少數殘留 family」 | 仍靠 downstream suppression，根因還沒被拿掉 |
| `shell_v3` | 把 upstream seam topology 修正到 downstream suppression 變成 no-op，並凍結乾淨 geometry baseline | 這條線仍是 prism-less tetra near-wall，不適合直接當 BL route |
| `shell_v4` | 正式把問題改寫成 half-wing boundary-layer / solver-validation 路線，並證明 real SST run 可啟動 | real-wing 主線目前卡在新的 3D volume-side family，還不能當 production-ready BL pipeline |

### 整條線最重要的工程判讀

- `shell_v1 / v2` 的主題是「把壞掉的 tip-end geometry 用 downstream 幾何補救先壓住」。
- `shell_v3` 的主題是「證明真正該修的是 upstream seam truth，而不是一直疊 downstream patch」。
- `shell_v4` 的主題是「geometry baseline 既然已經夠乾淨，就不要再拿 prism-less tetra shell 假裝 near-wall；要換 route」。

所以：

- `v3` 是 geometry baseline 的完成態。
- `v4` 是 near-wall / BL / solver-validation 的新起點，不是 `v3` 的小修版。

## v1 到 v4 的詳細脈絡

## shell_v1

### 這一代想解的問題

最早的核心問題是：

- `esp_rebuilt main_wing` 雖然能 materialize geometry，
- 但 tip-end terminal strip / trailing-edge seam 附近會產生非常不健康的細長面與 sliver family，
- 導致 3D tetra volume mesh 雖然可能生成，但品質非常差。

這一代的目標不是高品質 CFD，
而是先把流程推到「有完整 3D volume smoke」。

### 這一代用了什麼方法

依現存 artifact 看，
`shell_v1` 屬於第一代 downstream `terminal strip suppression` 路線：

- 在 provider / normalized geometry 之後，
- 對 tip terminal source section 做局部 strip suppression，
- 先把最糟的 terminal strip 幾何壓掉，
- 換到比較能被 Gmsh 吃下去的形狀。

這條路線的本質是：
先 patch tip-end 幾何，讓 volume smoke 能跑完。

### 這一代得到的結果

`shell_v1_strip_suppression` 現存 smoke artifact 顯示：

- `surface_element_count = 107250`
- `volume_element_count = 129094`
- `nodes_created_per_boundary_node = 0.02553`
- `ill_shaped_tet_count = 39`
- `min_gamma = 1.146e-4`
- suppression report:
  `applied = true`, `suppressed_source_section_count = 1`
- hotspot family 仍集中在 tip-adjacent surfaces:
  `32 / 30 / 31 / 10`

### 這一代真正學到的事

`shell_v1` 的價值不是品質，
而是證明：

- 路線不是完全不通
- 主問題確實集中在 tip-end family
- 局部 suppression 能讓 3D smoke 出來

### 為什麼要進到 v2

因為 `39` 個 ill-shaped tets 太多，
這代表：

- 路線只是「勉強能跑」
- 不是可比較的 baseline
- 更不是可以往 solver 去的幾何基礎

所以 `v2` 的工作不是改方向，
而是把同一個 tip-end family 再壓乾淨一層。

## shell_v2

### 這一代想解的問題

`v2` 直接接在 `v1` 後面，
要處理的是：

- `v1` 已經知道主要壞在 tip-end sliver family
- 但 downstream suppression 還不夠乾淨
- 需要一個更穩、可比較、可當 control 的 baseline

### 這一代用了什麼方法

`shell_v2_strip_suppression` 是更成熟的 downstream tip suppression baseline：

- 仍然站在 `terminal strip suppression` 這條思路上
- 但 suppress 的目標面 family 和局部幾何控制更穩定
- 最後形成一個可被後續 `tip_quality_buffer`、`sliver pocket`、`autonomous upstream repair` 全部引用的控制基線

也可以把 `v2` 看成：
第一個真的可以拿來做「後續所有比較」的 main-wing 3D baseline。

### 這一代得到的結果

`shell_v2_strip_suppression` 的關鍵結果是：

- `surface_element_count = 107338`
- `volume_element_count = 129288`
- `nodes_created_per_boundary_node = 0.02605`
- `ill_shaped_tet_count = 5`
- `min_gamma = 1.700e-4`
- suppression report:
  `applied = true`, `suppressed_source_section_count = 1`
- seam-adjacent edge lengths約 `1.93 mm / 1.86 mm`
- hotspot family 很明確收斂在：
  `30 / 21 / 31 / 32`

### 這一代真正完成了什麼

`v2` 的最大貢獻是：

- 把 `ill_shaped_tet_count` 從 `39` 壓到 `5`
- 把問題從「整個 route 都不可靠」縮成「少數 tip family 的殘留病灶」
- 給後面的實驗一個很清楚的對照基準

所以 `v2` 雖然不是 final baseline，
但它其實是第一個有工程價值的 control case。

### 這一代沒完成什麼

`v2` 沒解掉的，是更關鍵的一件事：

- 它仍然靠 downstream suppression 才活得下來

也就是說：

- 問題被壓住了
- 但 upstream geometry truth 還沒被修正

這就是 `v3` 必須出現的原因。

## shell_v3

`shell_v3` 其實不是單一招，
而是一整個轉折期。

如果高角度來看，
`v3` 做了三件不同層次的事：

1. 測試「只靠 meshing/local field 能不能把 v2 剩下的病灶清乾淨」
2. 把根因往 upstream seam topology 推
3. 凍結 geometry baseline，讓 solver/CFD work 從此不再重開舊 geometry 問題

### v3-A: meshing-only 補救嘗試，證明它不夠

這一段包含：

- `tip_quality_buffer` candidates
- `sliver_volume_pocket` 類型的 volume-side mesh pocket
- bounded autonomous upstream repair controller 的診斷前置

這些嘗試都在回答同一個問題：

> 如果不改 upstream truth，只靠 local field / meshing policy，能不能把 `v2` 最後那個 family 做乾淨？

答案基本上是：不能。

`tip_quality_buffer_summary.json` 顯示：

- `shell_v3_tipbuf_h8 / h6 / h4` 全都沒有過 quality-clean gate
- 共同卡點都是：
  `ill_shaped_tets_present`
- expanded 版本甚至更差，會把 ill-shaped tet 拉回 `10`

這一步的價值不在於成功，
而在於很清楚地證明：

- 剩下那個 family 不是單純 mesh-field tuning 能吃掉的
- 真正問題還在 upstream geometry / seam truth

### v3-B: upstream seam coalesce，真正把根因往前推

這是 `v3` 最關鍵的一步。

透過 `_coalesce_trailing_edge_seam()`，
pipeline 把 tip-end trailing-edge seam 的處理往 upstream 移，
結果是：

- downstream `shell_v2` suppression 不再是 active fix
- 它變成 honest no-op

這件事非常重要，
因為它代表：

- 問題不是「要不要 suppress 更多」
- 而是「原始 seam topology 有沒有先被修好」

### v3-C: 形成 `shell_v3_quality_clean_baseline`

這個 baseline 是整條線第一次可以說
「geometry 這一題先收住」的版本。

關鍵結果：

- `surface_triangle_count = 109896`
- `volume_element_count = 132499`
- `nodes_created_per_boundary_node = 0.024221`
- `ill_shaped_tet_count = 0`
- `min_gamma = 0.0017379`
- `min_sicn = 0.001600`
- `min_sige = 0.04934`
- Gmsh log 明確出現：
  `No ill-shaped tets in the mesh :-)`
- suppression report:
  `applied = false`
- seam-adjacent edge lengths約 `17.09 mm / 16.58 mm`
  已遠大於 suppression threshold `2.61 mm`
- 舊的 `30 / 21` sliver family 不再主導，
  剩下的 tip hotspot 縮到 `31 / 32`

### v3 的真正意義

`v3` 真正完成的不是「再做出一個比較好的 mesh」，
而是完成以下三件事：

1. 把 downstream patch 退位成 no-op
2. 建立一個可凍結的 geometry truth
3. 讓後續 solver / near-wall / BL work 可以正式說：
   「不要再回頭重開這個 geometry bug」

### v3 的 CFD / solver 面結果

在 geometry baseline 凍結之後，
`v3` 還建立了 package-native SU2 coarse baseline：

- 使用 frozen mesh
- 改成 `adiabatic_no_slip / MARKER_HEATFLUX`
- 避免舊的 slip-like `MARKER_EULER` 路線產生負 drag

這一步把 `v3` 從單純 mesh baseline 推到 coarse CFD baseline。

但 `v3` 也很清楚地碰到極限：

- 這條線本質上仍是 prism-less tetra near-wall route
- `near_wall_capability_report.v1` 已明確判斷：
  `prism_layer_not_yet_feasible_use_refined_tetra_fallback`
- bounded near-wall candidates 甚至出現
  `volume_element_count = 0`

### 為什麼要進到 v4

因為到這裡，工程判斷已經很明確：

- `v3` 的 geometry baseline 已經夠乾淨
- 但它不是一條 honest boundary-layer route

也就是說，
若還想繼續用 `v3` 直接加 BL，
那不是延續主線，而是在錯的 route 上硬撐。

所以 `v4` 不是 bugfix，
是換 route。

## shell_v4

### 這一代想解的問題

`v4` 的出發點是：

> 既然 `v3` 已經把 geometry baseline 收乾淨，就不要再假裝 prism-less tetra shell 可以代表 near-wall / BL。

所以 `v4` 的核心是：

- half-wing
- explicit boundary-layer cells
- Mac-safe memory / cell-budget / solver route
- 真正面向 solver-validation，而不是只做 geometry smoke

### v4 一開始真正解掉的東西

`shell_v4_half_wing_bl_mesh_macsafe` 的前半段成功把幾件結構性問題分開了：

1. 建立新的 half-wing BL mesh spec
2. 把 off-wall volumetric refinement 與 near-wall support field 正式化
3. 改用 BL-generated faces 處理 real main-wing root closure
4. 把 solver route 切到可控的 MPI / OpenMP contract

這條線後來也成功得到第一批 real solver evidence：

- prelaunch mesh:
  `1,175,040` total cells
- nodes:
  `483,656`
- estimated RAM 約 `9.87 GB`
- `bl_achieved_layers = 24`
- `bl_collapse_rate = 0.0`
- 第一個 real SST solver validation run 完成 `500` iterations
- final coefficients:
  `CL = 0.05408`
  `CD = 0.23326`
  `CM = -0.03988`

但這一輪被正確地定義成：

- `trend_only`
- 不是 production aerodynamic evidence

因為：

- `Cauchy[CL]` 仍在 drift
- last-window force variation 還太大
- wall diagnostics contract 也還不完整

### v4 的後半段：real-wing 幾何 / topology 問題重新浮出來

一旦 `v4` 不再是 surrogate，而是走真實主翼，
新的 blocker family 開始出現。

這些 family 不再是 `v1/v2/v3` 那種 tip strip suppression 問題，
而是 BL route 自己才會碰到的 topology contract 問題：

1. real-wing root closure contract
2. truncation seam local protection
3. required closure ring face family
4. collapsed triangular end-cap / degenerated prism family
5. 後續新的 3D volume-side PLC family

### v4 已經完成的 class-level 修正

到 2026-04-23 這個節點，
`v4` 這條線已經不是逐面打補丁，
而是有幾個明確的 class-level fix：

#### 1. root closure

- 不再走 holed symmetry face
- 改成使用 BL-generated faces 關閉 real-wing root closure

#### 2. truncation seam required closure ring family

`353 / 383 / 410 / 427 / 471`
不再被當成單一壞面，
而是被定義成：

`truncation seam required closure ring face family`

後來也已經從：

- single-face patch

改成：

- `closure family -> oriented patch descriptor -> exact 4-edge wire -> surface filling`

這代表：

- `353` 不再是 special-case
- 舊的 closure-ring ordering 問題已經被提升成 class-level fix

#### 3. collapsed triangular end-cap family

在 closure ring family 修掉後，
新冒出的第一個 family 是：

- `degenerated prism`
- `Could not recover boundary mesh: error 2`

工程判讀是：

- 這不是舊的 closure-ring family
- 而是 collapsed edge / triangular end-cap / volume-side contract 問題

這一輪已經做過一次嚴格受限的 family-level fix：

- 辨識「3 張 patch 全部 collapsed 的 triangular end-cap 子族群」
- 對這個 family 直接 fallback 到原 extBL termination
- 不再硬做 local closure-block rebuild

這個修法已經把 pipeline 從原本那個 closure-block family 推開。

### v4 目前真正停在哪裡

依 2026-04-23 這輪驗證，
`v4` real-wing prelaunch 還沒有 clean。

但重點不是「還沒 clean」，
而是第一個 failure family 已經換了：

- 舊的 closure-ring / triangular-end-cap family 不再是第一個主 blocker
- 新的第一個 failure family 變成：
  `PLC Error: A segment and a facet intersect at point`
- 同時伴隨：
  `Degenerated prism in extrusion of volume ...`

這代表什麼？

代表 `v4` 已經把問題推進到新的層級：

- 不再是 2D closure ring ordering
- 不再是 connector-side closure patch family
- 而是更後面的 3D volume-side / solver-entry topology family

這也就是為什麼目前正確的決策不是再沿著同一方向繼續 mainline generalization，
而是依 stopping rule 轉成新的 solver-entry / 3D volume-side branch。

## 從更高角度看，這條 pipeline 到底在做什麼

如果只看 commit，很容易覺得這條線很亂。

但從工程結構看，其實非常一致：

### 第一層：先讓它能出 volume

這是 `v1`

- 目標不是漂亮
- 是先活下來

### 第二層：把問題縮成明確 family

這是 `v2`

- 從很多壞 tet
- 收斂到少數 tip family

### 第三層：證明根因在 upstream geometry truth

這是 `v3`

- 把 downstream patch 退位
- 把 seam topology 修正成 source truth
- 再把 geometry baseline 凍結

### 第四層：換成真正能談 near-wall / BL 的新 route

這是 `v4`

- 不再假裝 tetra shell 是 boundary-layer route
- 直接承認要換 half-wing BL pipeline

### 第五層：開始碰到真正高階的 BL / volume-side family

這就是 `v4` 現在的狀態

- blocker 已經不是 tip strip suppression 了
- 也不是 seam coalesce 了
- 而是 boundary-layer / truncation / volume-entry contract

這說明 pipeline 其實是在前進，
只是前進的方式不是「一路 success」，
而是每次都把 failure family 往更後、更本質的層級推。

## 現在應該怎麼看這條線

### `shell_v3` 應該被當成什麼

`shell_v3` 應該被當成：

- geometry truth / frozen baseline
- coarse CFD baseline
- regression reference

它不是最終 near-wall 路線，
但它是你現在所有 solver / validation work 的穩定參考點。

### `shell_v4` 應該被當成什麼

`shell_v4` 應該被當成：

- active BL / near-wall / solver-validation branch
- 用來探索真實主翼 boundary-layer pipeline 會在哪些 family 爆掉

它現在不是 production route，
但它已經證明這條路是真的在逼近 production 問題，
因為 blocker 已經來到 3D volume-side / solver-entry 這一層。

## 最後的工程結論

### 1. 這條 pipeline 並沒有在原地打轉

它其實很清楚地完成了這個推進鏈：

`v1`
大量壞 tet，但 volume smoke 可跑

`v2`
把大量壞 tet 壓成少數殘留 family

`v3`
把根因從 downstream suppression 推回 upstream seam truth，得到 frozen clean baseline

`v4`
在 frozen geometry 之上另開真正的 BL / solver-validation route，並把 blocker 推到新的 3D volume-side family

### 2. `v3` 與 `v4` 不該互相取代

最正確的分工是：

- `v3` 保持 frozen baseline
- `v4` 繼續當 active BL branch

不要再讓 `v4` 回頭變 geometry baseline，
也不要讓 `v3` 硬撐成 BL route。

### 3. 目前最合理的下一步

依現在 evidence，
下一步不應該再把 `v4` 同方向一路 generalize 下去，
而應該明確切成新的 branch：

- `solver-entry / 3D volume-side contract branch`

因為到這個節點，
mainline 已經完成它這一輪該完成的工作：

- 把舊 family 推掉
- 揭露新 family
- 證明新的問題確實已經換層

這就是這條 pipeline 到今天最值得保留的高角度判讀。
